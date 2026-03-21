#!/usr/bin/env python3
import glob
import json
import os.path
import shutil
import subprocess
import time
import threading

import gpiod

import misc
from logutil import get_logger

logger = get_logger(__name__)

pin = None


class Pwm:
    def __init__(self, chip):
        self.period_value = None
        try:
            int(chip)
            chip = f'pwmchip{chip}'
        except ValueError:
            pass
        self.filepath = f"/sys/class/pwm/{chip}/pwm0/"
        try:
            with open(f"/sys/class/pwm/{chip}/export", 'w') as f:
                f.write('0')
        except OSError:
            logger.exception('Warning: init pwm error for chip=%s', chip)

    def period(self, ns: int):
        self.period_value = ns
        with open(os.path.join(self.filepath, 'period'), 'w') as f:
            f.write(str(ns))

    def period_us(self, us: int):
        self.period(us * 1000)

    def enable(self, t: bool):
        with open(os.path.join(self.filepath, 'enable'), 'w') as f:
            f.write(f"{int(t)}")

    def write(self, duty: float):
        assert self.period_value, "The Period is not set."
        with open(os.path.join(self.filepath, 'duty_cycle'), 'w') as f:
            f.write(f"{int(self.period_value * duty)}")


class Gpio:

    def tr(self):
        while True:
            self.line_request.set_value(self.line_offset, gpiod.line.Value.ACTIVE)
            time.sleep(self.value[0])
            self.line_request.set_value(self.line_offset, gpiod.line.Value.INACTIVE)
            time.sleep(self.value[1])

    def __init__(self, period_s):
        chip_path = os.environ['FAN_CHIP']
        if not chip_path.startswith('/dev/'):
            chip_path = f'/dev/gpiochip{chip_path}'
        self.line_offset = int(os.environ['FAN_LINE'])
        self.line_request = gpiod.request_lines(
            chip_path,
            consumer='fan',
            config={
                self.line_offset: gpiod.LineSettings(
                    direction=gpiod.line.Direction.OUTPUT,
                    output_value=gpiod.line.Value.INACTIVE
                )
            }
        )
        self.value = [period_s / 2, period_s / 2]
        self.period_s = period_s
        self.thread = threading.Thread(target=self.tr, daemon=True)
        self.thread.start()

    def write(self, duty):
        self.value[1] = duty * self.period_s
        self.value[0] = self.period_s - self.value[1]


def read_cpu_temp():
    with open('/sys/class/thermal/thermal_zone0/temp') as f:
        t = int(f.read().strip()) / 1000.0
    return t


def read_disk_temp_sysfs(device):
    for path in sorted(glob.glob(f'/sys/block/{device}/device/hwmon/hwmon*/temp*_input')):
        with open(path) as f:
            return int(f.read().strip()) / 1000.0
    return None


def read_disk_temp_smart(device):
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


def read_disk_temp(device):
    try:
        temp = read_disk_temp_sysfs(device)
        if temp is not None:
            return temp
    except (OSError, ValueError):
        logger.debug('Disk temperature sysfs read failed for %s', device, exc_info=True)

    try:
        temp = read_disk_temp_smart(device)
        if temp is not None:
            return float(temp)
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError):
        logger.debug('Disk temperature SMART read failed for %s', device, exc_info=True)

    return None


def read_fan_source_temp():
    if misc.conf['fan']['source'] != 'disk':
        temp = read_cpu_temp()
        return temp, 'cpu', {'cpu': temp}

    disk_temps = {}
    for device in misc.conf['fan']['disk']:
        temp = read_disk_temp(device)
        if temp is not None:
            disk_temps[device] = temp

    if disk_temps:
        temp = max(disk_temps.values())
        return temp, 'disk', disk_temps

    logger.warning(
        'Disk temperature source selected but no configured disk temperatures were readable; falling back to CPU'
    )
    temp = read_cpu_temp()
    return temp, 'cpu-fallback', {'cpu': temp}


def get_dc(cache={}):
    if misc.conf['run'].value == 0:
        return 0.999

    if time.time() - cache.get('time', 0) > 60:
        temp, source, readings = read_fan_source_temp()
        dc = misc.fan_temp2dc(temp)
        cache['time'] = time.time()
        cache['dc'] = dc
        logger.debug(
            'Fan reading: source=%s readings=%s selected_temp_c=%.2f target_dc=%.3f run=%s',
            source,
            readings,
            temp,
            dc,
            bool(misc.conf['run'].value),
        )

    return cache['dc']


def change_dc(dc, cache={}):
    if dc != cache.get('dc'):
        cache['dc'] = dc
        pin.write(dc)
        logger.debug('Fan output updated: duty_cycle=%.3f', dc)


def running():
    global pin
    if os.environ['HARDWARE_PWM'] == '1':
        chip = os.environ['PWMCHIP']
        logger.info(
            'Fan init: mode=hardware pwmchip=%s period_us=40 source=%s disks=%s',
            chip,
            misc.conf['fan']['source'],
            misc.conf['fan']['disk'],
        )
        pin = Pwm(chip)
        pin.period_us(40)
        pin.enable(True)
    else:
        chip_path = os.environ['FAN_CHIP']
        line_offset = os.environ['FAN_LINE']
        logger.info(
            'Fan init: mode=software chip=%s line=%s period_s=0.025 source=%s disks=%s',
            chip_path,
            line_offset,
            misc.conf['fan']['source'],
            misc.conf['fan']['disk'],
        )
        pin = Gpio(0.025)
    logger.info('Fan initialization completed')
    while True:
        change_dc(get_dc())
        time.sleep(1)


if __name__ == '__main__':
    running()
