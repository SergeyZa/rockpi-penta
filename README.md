# ROCK Pi Penta SATA

Top Board control program

[Penta SATA HAT wiki](<https://wiki.radxa.com/Penta_SATA_HAT>)

[Penta SATA HAT docs](https://docs.radxa.com/en/accessories/penta-sata-hat)

![penta-hat](images/penta-sata-hat.png)

## Requirements

- Python 3
- python3-libgpiod >= 2.0
- python3-pillow
- adafruit-circuitpython-ssd1306 (for OLED; fan-only mode works without it)

Install runtime dependencies:

```bash
sudo apt install python3-libgpiod python3-pillow python3-pip
pip3 install adafruit-circuitpython-ssd1306
```

## Run from Source (for testing)

Stop the installed service first if it is running:

```bash
sudo systemctl stop rockpi-penta.service || true
```

Run using the helper script (defaults to Raspberry Pi 5 env):

```bash
sudo ./run-from-source.sh            # uses rpi5.env
sudo ./run-from-source.sh rpi4.env   # or specify another board
```

Or manually:

```bash
cd rockpi-penta/usr/bin/rockpi-penta
set -a && . env/rpi5.env && set +a
python3 main.py
```

Available env files: `rpi5.env`, `rpi4.env`, `rock_5a.env`, `rock_5a_armbian.env`,
`rock_3c.env`, `rock_pi_3.env`, `rock_pi_4.env`, `rock_pi_4_armbian.env`.

### Button pull-up bias

The env files set `BUTTON_BIAS=pull_up` by default, which enables an internal
pull-up resistor on the button GPIO line. If your board's GPIO controller does
not support software-controlled bias, change it in the env file:

| Value       | Behaviour                              |
|-------------|----------------------------------------|
| `pull_up`   | Enable internal pull-up (default)      |
| `pull_down` | Enable internal pull-down              |
| `disabled`  | Explicitly disable internal bias       |
| `as_is`     | Leave bias at whatever the hardware defaults to |

## Config Reference

Runtime configuration is loaded from `/etc/rockpi-penta.conf`.

### `/etc/rockpi-penta.conf`

```ini
[fan]
lv0 = 35
lv1 = 40
lv2 = 45
lv3 = 50

[key]
click = slider
twice = switch
press = none

[time]
twice = 0.7
press = 1.8

[slider]
auto = true
time = 10

[oled]
rotate = false
f-temp = false
```

`[fan]`

| Key | Type | Meaning | Sample |
|-----|------|---------|--------|
| `lv0` | number | Temperature threshold for 25% fan power | `35` |
| `lv1` | number | Temperature threshold for 50% fan power | `40` |
| `lv2` | number | Temperature threshold for 75% fan power | `45` |
| `lv3` | number | Temperature threshold for 100% fan power | `50` |

`[key]`

| Key | Type | Allowed values | Sample |
|-----|------|----------------|--------|
| `click` | string | `none`, `slider`, `switch`, `reboot`, `poweroff` | `slider` |
| `twice` | string | `none`, `slider`, `switch`, `reboot`, `poweroff` | `switch` |
| `press` | string | `none`, `slider`, `switch`, `reboot`, `poweroff` | `none` |

`[time]`

| Key | Type | Meaning | Sample |
|-----|------|---------|--------|
| `twice` | number (seconds) | Max interval between two clicks | `0.7` |
| `press` | number (seconds) | Long-press detection time | `1.8` |

`[slider]`

| Key | Type | Allowed values | Sample |
|-----|------|----------------|--------|
| `auto` | boolean | `true` / `false` | `true` |
| `time` | number (seconds) | Delay before auto-advancing page | `10` |

`[oled]`

| Key | Type | Allowed values | Sample |
|-----|------|----------------|--------|
| `rotate` | boolean | `true` / `false` | `false` |
| `f-temp` | boolean | `true` / `false` | `false` |

### Environment File Values

Board-specific env files are under `rockpi-penta/usr/bin/rockpi-penta/env/`.

| Key | Type | Meaning | Sample |
|-----|------|---------|--------|
| `SDA` | string | Board-specific I2C SDA pin name | `SDA` |
| `SCL` | string | Board-specific I2C SCL pin name | `SCL` |
| `OLED_RESET` | string | Board-specific OLED reset pin name | `D23` |
| `BUTTON_CHIP` | integer or `/dev/gpiochipN` | GPIO chip for button input | `4` |
| `BUTTON_LINE` | integer | GPIO line offset for button input | `17` |
| `BUTTON_BIAS` | string | `pull_up`, `pull_down`, `disabled`, `as_is` | `pull_up` |
| `FAN_CHIP` | integer or `/dev/gpiochipN` | GPIO chip for software PWM fan control | `4` |
| `FAN_LINE` | integer | GPIO line offset for software PWM fan control | `27` |
| `HARDWARE_PWM` | integer | `1` = hardware PWM mode, `0` = GPIO software PWM mode | `0` |
| `PWMCHIP` | integer | PWM chip index used when `HARDWARE_PWM=1` | `14` |

## Build DEB Package

```bash
chmod -R 775 rockpi-penta/DEBIAN/
dpkg-deb --build -Z gzip rockpi-penta
```

This produces `rockpi-penta.deb` in the repo root.

## Install / Upgrade

```bash
sudo dpkg -i rockpi-penta.deb
sudo apt-get install -f   # fix any missing dependencies
```

The postinst script detects your board, copies the matching env file to
`/etc/rockpi-penta.env`, enables and starts the systemd service.

## Uninstall

```bash
sudo dpkg -r rockpi-penta
```

## Troubleshooting

```bash
# Check service status
sudo systemctl status rockpi-penta.service

# View live logs
sudo journalctl -u rockpi-penta.service -f

# Verify gpiod v2 is available
python3 -c "import gpiod; print(gpiod.__version__)"
```
