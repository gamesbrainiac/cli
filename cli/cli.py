# -*- coding: utf-8 -*-

import json
import os
import subprocess
import sys
import time
from urllib.parse import urlencode
from uuid import uuid4

import click

import click_help_colors

import click_spinner

import emoji

from raven import Client

import requests

from .helpers.didyoumean import DYMGroup
from .version import version


if not os.getenv('TOXENV'):
    enable_reporting = True
    sentry = Client(
        'https://007e7d135737487f97f5fe87d5d85b55@sentry.io/1206504'
    )
else:
    enable_reporting = False
    sentry = Client()

data = None
home = os.path.expanduser('~/.asyncy')


def get_access_token():
    return data['access_token']


def track_profile():
    _make_tracking_http_request(
        'https://stories.asyncyapp.com/track/profile', {
            'id': str(data['id']),
            'profile': {
                'Name': data['name'],
                'Email': data.get('email'),
                'GitHub Username': data.get('username'),
                'Timezone': time.tzname[time.daylight]
            }
        })


def _make_tracking_http_request(url, json_data):
    """
    Forks the HTTP call into the background.
    The caller does not make the call, and this method returns just after
    forking the process.

    The child makes the call, and does not return back to the caller,
    but instead just exits (sys.exit(0)). This is to ensure that whatever
    needs to happen after this method is called, does not happen twice.
    """
    if not enable_reporting:
        return
    if sys.platform != 'linux' and sys.platform != 'darwin':
        try:
            requests.post(url, json=json_data)
        except Exception:
            # ignore issues with tracking
            pass

        return

    pid = os.fork()
    if pid > 0:
        # This is the parent process.
        return

    try:
        requests.post(url, json=json_data)
    except Exception:
        # ignore issues with tracking
        pass

    # This is the child process. Exit now.
    sys.exit(0)


def track(event_name, extra: dict = None):
    if extra is None:
        extra = {}

    extra['CLI version'] = version
    _make_tracking_http_request(
        'https://stories.asyncyapp.com/track/event', {
            'id': str(data['id']),
            'event_name': event_name,
            'event_props': extra
        })


def find_asyncy_yml():
    current_dir = os.getcwd()
    while True:
        if os.path.exists(f'{current_dir}{os.path.sep}asyncy.yml'):
            return f'{current_dir}/asyncy.yml'
        elif current_dir == os.path.dirname(current_dir):
            break
        else:
            current_dir = os.path.dirname(current_dir)

    return None


def get_app_name_from_yml() -> str:
    file = find_asyncy_yml()
    if file is None:
        return None
    import yaml
    with open(file, 'r') as s:
        return yaml.load(s).pop('app_name')


def get_asyncy_yaml() -> dict:
    file = find_asyncy_yml()
    # Anybody calling this must've already checked for this file presence.
    assert file is not None

    import yaml
    with open(file, 'r') as s:
        return yaml.load(s)


def write(content: str, location: str):
    dir = os.path.dirname(location)
    if dir and not os.path.exists(dir):
        os.makedirs(dir)

    if isinstance(content, (list, dict)):
        content = json.dumps(content, indent=2)

    with open(location, 'w+') as file:
        file.write(content)


def initiate_login():
    global data

    click.echo(
        'Hi! Thank you for using ' +
        click.style('Asyncy', fg='magenta') + '.'
    )
    click.echo('Please login with GitHub to get started.')

    state = uuid4()

    query = {
        'state': state
    }

    url = f'https://stories.asyncyapp.com/github?{urlencode(query)}'

    click.launch(url)
    click.echo()
    click.echo('Visit this link if your browser '
               'doesn\'t open automatically:')
    click.echo(url)
    click.echo()

    while True:
        with click_spinner.spinner():
            try:
                url = 'https://stories.asyncyapp.com/github/oauth_callback'

                res = requests.get(f'{url}?state={state}')

                if res.text == 'null':
                    raise IOError()

                res.raise_for_status()
                break
            except IOError:
                time.sleep(0.5)
            except KeyboardInterrupt:
                click.echo('Login failed. Please try again.')
                sys.exit(1)

    if res.json().get('beta') is False:
        click.echo(
            'Hello! Asyncy is in private beta at this time.')
        click.echo(
            'We\'ve added you to our beta testers queue, '
            'and you should hear from us\nshortly via email'
            ' (which is linked to your GitHub account).'
        )
        sys.exit(1)

    write(res.text, f'{home}/.config')
    init()

    click.echo(
        emoji.emojize(':waving_hand:') +
        f'  Welcome {data["name"]}!'
    )
    click.echo()
    click.echo('Create a new app with:')
    print_command('asyncy apps create')

    click.echo()

    click.echo('To list all your apps:')
    print_command('asyncy apps')

    click.echo()
    track('Login Completed')
    track_profile()


def user() -> dict:
    """
    Get the active user.
    """
    global data

    if data:
        return data
    else:
        initiate_login()
        return data


def print_command(command):
    click.echo(click.style(f'$ {command}', fg='magenta'))


def print_deprecated_warning(alternative):
    click.echo(click.style('Warning: ', fg='yellow') +
               'This command is deprecated and will be removed' +
               ' in a future release. Please use ' +
               click.style(f'$ {alternative}\n', fg='magenta'))


def assert_project(command, app, default_app, allow_option):
    if app is None:
        click.echo(click.style('No Asyncy application found.', fg='red'))
        click.echo()
        click.echo('Create an application with:')
        print_command('asyncy apps create')
        sys.exit(1)
    elif not allow_option and app != default_app:
        click.echo(click.style(
            'The --app option is not allowed with the {} command.'
            .format(command),
            fg='red'
        ))
        sys.exit(1)
    return app


def init():
    global data
    if os.path.exists(f'{home}/.config'):
        with open(f'{home}/.config', 'r') as file:
            data = json.load(file)
            sentry.user_context({
                'id': data['id'],
                'email': data['email']
            })


def stream(cmd: str):
    process = subprocess.Popen(cmd.split(' '), stdout=subprocess.PIPE)
    while True:
        output = process.stdout.readline()
        if output == b'' and process.poll() is not None:
            break
        if output:
            click.echo(output.strip())


def run(cmd: str):
    output = subprocess.run(
        cmd.split(' '),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    return str(output.stdout.decode('utf-8').strip())


# def _colorize(text, color=None):
#     # PATCH for https://github.com/r-m-n/click-help-colors/pull/3
#     from click.termui import _ansi_colors, _ansi_reset_all
#     if not color:
#         return text
#     try:
#         return '\033[%dm' % (_ansi_colors[color]) + text + _ansi_reset_all
#     except ValueError:
#         raise TypeError('Unknown color %r' % color)
#
#
# click_help_colors._colorize = _colorize


class Cli(DYMGroup, click_help_colors.HelpColorsGroup):
    pass


@click.group(cls=Cli,
             help_headers_color='yellow',
             help_options_color='magenta')
def cli():
    """
    Hello! Welcome to Asyncy

    We hope you enjoy and we look forward to your feedback.

    Documentation: https://docs.asyncy.com
    """
    init()
