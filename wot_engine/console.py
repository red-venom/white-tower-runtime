"""Interactive player shell over the existing public and offer/accept commands."""
from contextlib import redirect_stdout
from io import StringIO
import json
import secrets

from .player import choice_list, query
from .storage import private_directory


def run(directory, *, read=input, write=print):
    # Import lazily: the CLI also imports this entry point.
    from .__main__ import load_runtime, main
    directory, _, _, controller = load_runtime(directory)
    offer_directory = private_directory(directory / 'player-offers')

    def command(*args):
        output = StringIO()
        with redirect_stdout(output):
            code = main(list(args))
        return code, json.loads(output.getvalue())

    def show_scene():
        packet = controller.public_packet()
        p, w = packet['player'], packet['world']
        write(f"\n{p['name']} — {p['rank'].replace('_', ' ')}")
        write(f"{w['location']} · elapsed time {w['time_seconds']} seconds")
        write('Save status: ' + packet['status']['status'])
        write(w['scene_description'])
        for item in choice_list(controller):
            write(f"{item['number']}. {item['label']}")
        write('Enter a choice number, sheet, training, journal, show-roll, course N01, skip SECONDS, recap, or pause.')

    write('White Tower — rehearsal player console')
    write('Describe free-form intentions to your narrator; this console runs displayed choices and supported commands.')
    show_scene()
    while True:
        try:
            line = read('> ').strip()
        except (EOFError, KeyboardInterrupt):
            write('\nPaused. No new decision was accepted.')
            return 0
        if line in ('pause', 'quit', 'exit'):
            write('Paused. Fictional time does not advance while you are away.')
            return 0
        if line == 'recap':
            show_scene()
            continue
        if line in ('sheet', 'training', 'journal', 'show-roll', 'known-facts', 'weaves'):
            write(json.dumps(query(controller, line), ensure_ascii=False, indent=2))
            continue
        if line.startswith('course '):
            code, result = command('course', '--path', str(directory), '--course-id', line[7:].strip())
            write(json.dumps(result, ensure_ascii=False, indent=2))
            continue
        action_id = 'play-' + secrets.token_hex(12)
        offer = offer_directory / (action_id + '.json')
        common = ('--path', str(directory), '--action-id', action_id, '--output', str(offer))
        if line.isdecimal():
            code, result = command('choose', *common, '--choice', line)
        elif line.startswith('skip '):
            seconds = line[5:].strip()
            if not seconds.isdecimal():
                write('Use skip followed by a whole number of seconds.')
                continue
            # Validate before argparse: preserve the interactive shell on huge input.
            if len(seconds) > 5:
                write('Waiting supports 1–28800 seconds per offer.')
                continue
            code, result = command('skip-time', *common, '--seconds', seconds)
        else:
            write('Choose a displayed number or command. For another intention, ask your narrator to build its stakes.')
            continue
        if code or 'stakes' not in result:
            write(result.get('message', 'The offer could not be prepared.'))
            continue
        stakes = result['stakes']
        write(f"\n{stakes['goal']}\nTime: {stakes['time_seconds']} seconds")
        if stakes['check'] is not None:
            write('Check: ' + json.dumps(stakes['check'], ensure_ascii=False))
        if stakes['irreversible_risk']:
            write('Risk: ' + str(stakes['irreversible_risk']))
        for change in stakes['upfront_resources']:
            write(f"{change['who']} {change['resource']}: {change['before']} → {change['after']}")
        for outcome, data in stakes['outcomes'].items():
            write(f"{outcome}: {data['summary']}")
            for change in data['resource_changes']:
                write(f"  {change['who']} {change['resource']}: {change['before']} → {change['after']}")
        try:
            accepted = read('Take this action? [yes/no] ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            write('\nPaused. This offer was not accepted.')
            return 0
        if accepted not in ('yes', 'y'):
            write('Offer declined. No time or resources spent.')
            continue
        code, result = command('accept', '--path', str(directory), '--offer', str(offer),
                               '--acceptance-ref', 'console-' + action_id)
        if result.get('status') == 'PENDING':
            write('Save pending. Your accepted action is retained. The operator must finish verification before play continues.')
            return 0
        if code or result.get('status') != 'OK':
            write(result.get('message', 'The action is not released. Check save status before continuing.'))
            continue
        write(result.get('narration') or 'Action saved and verified.')
        write('Save receipt: ' + result['receipt_id'])
        show_scene()
