#!/usr/bin/env python3
import fcntl
import os
import queue
import sys
import threading
import time

import fan
import misc
from logutil import get_logger, setup_logging

setup_logging(misc.conf['log']['level'])
logger = get_logger(__name__)

oled = None
top_board = False


def acquire_single_instance_lock():
    lock_path = os.environ.get('ROCKPI_PENTA_LOCK', '/tmp/rockpi-penta.lock')
    fd = open(lock_path, 'w')
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.error(
            'Another rockpi-penta instance is already running (lock=%s). '
            'Stop the service or existing process before starting a second instance.',
            lock_path,
        )
        return None
    fd.write(str(os.getpid()))
    fd.flush()
    return fd

q = queue.Queue()
lock = threading.Lock()

action = {
    'none': lambda: 'nothing',
    'slider': lambda: oled.slider(lock),
    'switch': lambda: misc.fan_switch(),
    'reboot': lambda: misc.check_call('reboot'),
    'poweroff': lambda: misc.check_call('poweroff'),
}


def receive_key(q):
    while True:
        key_event = q.get()
        func = misc.get_func(key_event)
        logger.debug('Dispatch key event: event=%s action=%s', key_event, func)
        action[func]()


if __name__ == '__main__':
    instance_lock = acquire_single_instance_lock()
    if instance_lock is None:
        sys.exit(1)

    try:
        import oled as oled_module
        oled = oled_module
        top_board = True
    except RuntimeError as ex:
        logger.warning('%s; service will run in fan-only mode', ex)
        top_board = False
    except Exception:
        logger.exception('OLED import failed, service will run in fan-only mode')
        top_board = False

    logger.info('Service startup: top_board=%s log.level=%s', top_board, misc.conf['log']['level'])

    if top_board:
        logger.info('Initializing OLED welcome screen')
        oled.welcome()
        p0 = threading.Thread(target=receive_key, args=(q,), daemon=True)
        p1 = threading.Thread(target=misc.watch_key, args=(q,), daemon=True)
        p2 = threading.Thread(target=oled.auto_slider, args=(lock,), daemon=True)
        p3 = threading.Thread(target=fan.running, daemon=True)

        logger.info('Starting worker threads: receive_key, watch_key, auto_slider, fan')
        p0.start()
        p1.start()
        p2.start()
        p3.start()
        time.sleep(0.2)
        logger.info(
            'Worker liveness: receive_key=%s watch_key=%s auto_slider=%s fan=%s',
            p0.is_alive(),
            p1.is_alive(),
            p2.is_alive(),
            p3.is_alive(),
        )
        if not p3.is_alive():
            logger.error(
                'Fan worker exited during startup. This usually means GPIO/PWM resources are busy.'
            )
        try:
            logger.info('Startup complete, waiting for fan thread')
            p3.join()
        except KeyboardInterrupt:
            logger.info('KeyboardInterrupt received, shutting down OLED')
            oled.goodbye()

    else:
        logger.info('Starting fan-only mode')
        p3 = threading.Thread(target=fan.running, daemon=False)
        p3.start()
        time.sleep(0.2)
        logger.info('Worker liveness: fan=%s', p3.is_alive())
        if not p3.is_alive():
            logger.error(
                'Fan worker exited during startup. Check for a running service or other GPIO users.'
            )
