#!/usr/bin/env python3
import glob
import json
import re
import os
import shutil
import time
import subprocess
import threading
import multiprocessing as mp

import gpiod
from configparser import ConfigParser
from collections import defaultdict, OrderedDict

from logutil import get_logger, setup_logging

logger = get_logger(__name__)

cmds = {
    'blk': "lsblk | awk '{print $1}'",
    'up': "echo Uptime: `uptime | sed 's/.*up \\([^,]*\\), .*/\\1/'`",
    'ip': "hostname -I | awk '{printf \"IP %s\", $1}'",
    'cpu': "uptime | awk '{printf \"CPU Load: %.2f\", $(NF-2)}'",
    'men': "free -m | awk 'NR==2{printf \"Mem: %s/%sMB\", $3,$2}'",
    'disk': "df -h | awk '$NF==\"/\"{printf \"Disk: %d/%dGB %s\", $3,$2,$5}'"
}

lv2dc = OrderedDict({'lv3': 0, 'lv2': 0.25, 'lv1': 0.5, 'lv0': 0.75})


def _normalize_fan_source(source):
    source = str(source).strip().lower()
    if source in ('cpu', 'disk'):
        return source
    return 'cpu'


def _parse_disk_list(value):
    if not value:
        return []
    return [item.strip() for item in value.split(',') if item.strip()]


def check_output(cmd):
    return subprocess.check_output(cmd, shell=True).decode().strip()


def check_call(cmd):
    return subprocess.check_call(cmd, shell=True)


def get_blk():
    conf['disk'] = [x for x in check_output(cmds['blk']).strip().split('\n') if x.startswith('sd')]


def get_info(s):
    return check_output(cmds[s])


def _read_cpu_temp_raw():
    with open('/sys/class/thermal/thermal_zone0/temp') as f:
        return int(f.read().strip()) / 1000.0


def _read_disk_temp_sysfs(device):
    for path in sorted(glob.glob(f'/sys/block/{device}/device/hwmon/hwmon*/temp*_input')):
        with open(path) as f:
            return int(f.read().strip()) / 1000.0
    return None


def _read_disk_temp_smart(device):
    smartctl = shutil.which('smartctl')
    if not smartctl:
        return None
    result = subprocess.run(
        [smartctl, '-Aj', f'/dev/{device}'],
        stderr=subprocess.DEVNULL,
        text=True,
        stdout=subprocess.PIPE,
        check=False,
    )
    if not result.stdout:
        return None
    return json.loads(result.stdout).get('temperature', {}).get('current')


def _read_disk_temp(device):
    try:
        temp = _read_disk_temp_sysfs(device)
        if temp is not None:
            return temp
    except (OSError, ValueError):
        logger.debug('Disk temperature sysfs read failed for %s', device, exc_info=True)
    try:
        temp = _read_disk_temp_smart(device)
        if temp is not None:
            return float(temp)
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError):
        logger.debug('Disk temperature SMART read failed for %s', device, exc_info=True)
    return None


def get_cpu_temp():
    t = get_cached('cpu_temp', 0.0)
    if conf['oled']['f-temp']:
        return "CPU Temp: {:.0f}\u00b0F".format(t * 1.8 + 32)
    else:
        return "CPU Temp: {:.1f}\u00b0C".format(t)


def read_conf():
    conf = defaultdict(dict)

    try:
        cfg = ConfigParser()
        cfg.read('/etc/rockpi-penta.conf')
        # fan
        conf['fan']['lv0'] = cfg.getfloat('fan', 'lv0')
        conf['fan']['lv1'] = cfg.getfloat('fan', 'lv1')
        conf['fan']['lv2'] = cfg.getfloat('fan', 'lv2')
        conf['fan']['lv3'] = cfg.getfloat('fan', 'lv3')
        conf['fan']['source'] = _normalize_fan_source(cfg.get('fan', 'source', fallback='cpu'))
        conf['fan']['disk'] = _parse_disk_list(cfg.get('fan', 'disk', fallback=''))
        # key
        conf['key']['click'] = cfg.get('key', 'click')
        conf['key']['twice'] = cfg.get('key', 'twice')
        conf['key']['press'] = cfg.get('key', 'press')
        # time
        conf['time']['twice'] = cfg.getfloat('time', 'twice')
        conf['time']['press'] = cfg.getfloat('time', 'press')
        # other
        conf['slider']['auto'] = cfg.getboolean('slider', 'auto')
        conf['slider']['time'] = cfg.getfloat('slider', 'time')
        conf['oled']['rotate'] = cfg.getboolean('oled', 'rotate')
        conf['oled']['f-temp'] = cfg.getboolean('oled', 'f-temp')
        conf['log']['level'] = cfg.get('log', 'level', fallback='INFO')
        conf['cache']['refresh'] = cfg.getfloat('cache', 'refresh', fallback=60.0)
    except Exception:
        logger.exception('Failed to read /etc/rockpi-penta.conf, using defaults')
        # fan
        conf['fan']['lv0'] = 35
        conf['fan']['lv1'] = 40
        conf['fan']['lv2'] = 45
        conf['fan']['lv3'] = 50
        conf['fan']['source'] = 'cpu'
        conf['fan']['disk'] = []
        # key
        conf['key']['click'] = 'slider'
        conf['key']['twice'] = 'switch'
        conf['key']['press'] = 'none'
        # time
        conf['time']['twice'] = 0.7  # second
        conf['time']['press'] = 1.8
        # other
        conf['slider']['auto'] = True
        conf['slider']['time'] = 15  # second
        conf['oled']['rotate'] = False
        conf['oled']['f-temp'] = False
        conf['log']['level'] = 'INFO'
        conf['cache']['refresh'] = 60.0

    return conf


def _get_button_bias():
    bias_name = os.environ.get('BUTTON_BIAS', 'pull_up').lower()
    bias_map = {
        'pull_up': gpiod.line.Bias.PULL_UP,
        'pull_down': gpiod.line.Bias.PULL_DOWN,
        'disabled': gpiod.line.Bias.DISABLED,
        'as_is': gpiod.line.Bias.AS_IS,
    }
    return bias_map.get(bias_name, gpiod.line.Bias.PULL_UP)


def watch_key(q=None):
    chip_name = os.environ['BUTTON_CHIP']
    if not chip_name.startswith('/dev/'):
        chip_name = f'/dev/gpiochip{chip_name}'
    line_offset = int(os.environ['BUTTON_LINE'])
    bias_name = os.environ.get('BUTTON_BIAS', 'pull_up').lower()
    bias = _get_button_bias()
    size = int(conf['time']['press'] * 10)
    wait = int(conf['time']['twice'] * 10)
    pattern = {
        'click': re.compile(r'1+0+1{%d,}' % wait),
        'twice': re.compile(r'1+0+1+0+1{3,}'),
        'press': re.compile(r'1+0{%d,}' % size),
    }

    logger.info(
        'Button watcher init: chip=%s line=%s bias=%s press_window=%s twice_window=%s',
        chip_name,
        line_offset,
        bias_name,
        size,
        wait,
    )

    with gpiod.request_lines(
        chip_name,
        consumer='hat_button',
        config={
            line_offset: gpiod.LineSettings(
                direction=gpiod.line.Direction.INPUT,
                bias=bias
            )
        }
    ) as line_request:
        s = ''
        while True:
            value = line_request.get_value(line_offset)
            s = s[-size:] + ('1' if value == gpiod.line.Value.ACTIVE else '0')
            for t, p in pattern.items():
                if p.match(s):
                    logger.debug('Button event detected: %s', t)
                    q.put(t)
                    s = ''
                    break
            time.sleep(0.1)


def get_disk_info():
    return get_cached('disk_usage', [('root',), ('N/A',)])


def slider_next(pages):
    conf['idx'].value += 1
    return pages[conf['idx'].value % len(pages)]


def slider_sleep():
    time.sleep(conf['slider']['time'])


def fan_temp2dc(t):
    for lv, dc in lv2dc.items():
        if t >= conf['fan'][lv]:
            return dc
    return 0.999


def fan_switch():
    conf['run'].value = not conf['run'].value


def get_func(key):
    return conf['key'].get(key, 'none')


_cache_lock = threading.Lock()
_cache = {}


def get_cached(key, default=None):
    with _cache_lock:
        return _cache.get(key, default)


def _refresh_data():
    data = {
        'cpu_temp': get_cached('cpu_temp', 0.0),
        'up': get_cached('up', ''),
        'ip': get_cached('ip', ''),
        'cpu': get_cached('cpu', ''),
        'men': get_cached('men', ''),
        'disk_usage': get_cached('disk_usage', [('root',), ('N/A',)]),
        'disk_temps': get_cached('disk_temps', {}),
    }

    try:
        data['cpu_temp'] = _read_cpu_temp_raw()
    except OSError:
        logger.debug('Cache refresh: cpu_temp read failed', exc_info=True)

    for key in ('up', 'ip', 'cpu', 'men'):
        try:
            data[key] = check_output(cmds[key])
        except Exception:
            logger.debug('Cache refresh: %s read failed', key, exc_info=True)

    try:
        get_blk()
        info = {}
        info['root'] = check_output("df -h | awk '$NF==\"/\"{printf \"%s\", $5}'")
        for x in conf['disk']:
            info[x] = check_output(
                "df -Bg | awk '$1==\"/dev/{}\" {{printf \"%s\", $5}}'".format(x)
            )
        data['disk_usage'] = list(zip(*info.items()))
    except Exception:
        logger.debug('Cache refresh: disk_usage read failed', exc_info=True)

    disk_temps = {}
    for device in conf['fan']['disk']:
        try:
            temp = _read_disk_temp(device)
            if temp is not None:
                disk_temps[device] = temp
        except Exception:
            logger.debug('Cache refresh: disk temp failed for %s', device, exc_info=True)
    data['disk_temps'] = disk_temps

    with _cache_lock:
        _cache.update(data)

    logger.debug(
        'Cache refreshed: cpu_temp=%s disk_temps=%s',
        data.get('cpu_temp'),
        data.get('disk_temps'),
    )


def _cache_refresh_loop():
    while True:
        time.sleep(conf['cache']['refresh'])
        try:
            _refresh_data()
        except Exception:
            logger.exception('Cache refresh loop error')


def start_cache():
    _refresh_data()
    t = threading.Thread(target=_cache_refresh_loop, daemon=True)
    t.start()
    logger.info('Cache started: refresh_interval=%ss', conf['cache']['refresh'])
    return t


conf = {'disk': [], 'idx': mp.Value('d', -1), 'run': mp.Value('d', 1)}
conf.update(read_conf())
setup_logging(conf['log']['level'])
logger.info(
    'Config loaded: fan=%s key=%s time=%s slider=%s oled=%s log.level=%s cache=%s',
    dict(conf['fan']),
    dict(conf['key']),
    dict(conf['time']),
    dict(conf['slider']),
    dict(conf['oled']),
    conf['log']['level'],
    dict(conf['cache']),
)
start_cache()
