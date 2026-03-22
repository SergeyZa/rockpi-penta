#!/usr/bin/env python3
import errno
import os.path
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
        try:
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
        except OSError as ex:
            if ex.errno == errno.EBUSY:
                raise RuntimeError(
                    f'Fan GPIO busy: chip={chip_path} line={self.line_offset}. '
                    'Another process is likely using the same GPIO.'
                ) from ex
            raise
        self.value = [period_s / 2, period_s / 2]
        self.period_s = period_s
        self.thread = threading.Thread(target=self.tr, daemon=True)
        self.thread.start()

    def write(self, duty):
        self.value[1] = duty * self.period_s
        self.value[0] = self.period_s - self.value[1]


def get_dc():
    if misc.conf['run'].value == 0:
        return 0.999

    if misc.conf['fan']['source'] == 'disk':
        disk_temps = misc.get_cached('disk_temps', {})
        if disk_temps:
            temp = max(disk_temps.values())
            source = 'disk'
        else:
            logger.warning(
                'Disk temperature source selected but no disk temperatures available; falling back to CPU'
            )
            temp = misc.get_cached('cpu_temp', 0.0)
            source = 'cpu-fallback'
    else:
        temp = misc.get_cached('cpu_temp', 0.0)
        source = 'cpu'

    dc = misc.fan_temp2dc(temp)
    logger.debug(
        'Fan reading: source=%s temp_c=%.2f target_dc=%.3f run=%s',
        source, temp, dc, bool(misc.conf['run'].value),
    )
    return dc


def change_dc(dc, cache={}):
    if dc != cache.get('dc'):
        cache['dc'] = dc
        pin.write(dc)
        logger.debug('Fan output updated: duty_cycle=%.3f', dc)


def running():
    global pin
    try:
        control_interval = max(10, float(misc.conf['cache']['refresh']))
    except Exception:
        control_interval = 60.0

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
        try:
            pin = Gpio(0.025)
        except RuntimeError as ex:
            logger.error('%s', ex)
            return
    logger.info('Fan initialization completed: control_interval=%ss', control_interval)
    while True:
        change_dc(get_dc())
        time.sleep(control_interval)


if __name__ == '__main__':
    running()
