#!/usr/bin/env python3
import queue
import threading
import time

import fan
import misc
from logutil import get_logger, setup_logging

setup_logging(misc.conf['log']['level'])
logger = get_logger(__name__)

try:
    import oled

    top_board = True
except Exception as ex:
    logger.exception('OLED import failed, service will run in fan-only mode')
    top_board = False

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
