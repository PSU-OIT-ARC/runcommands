from .misc import abort
from .printer import printer


def confirm(config, prompt='Really?', color='warning', yes_values=('y', 'yes'),
            abort_on_unconfirmed=False, abort_options=None):
    """Prompt for confirmation.

    Confirmation can be aborted by typing in a no value instead of one
    of the yes values or with Ctrl-C.

    Args:
        config (Mapping): Only used to format ``prompt``
        prompt (str): Prompt to present user ["Really?"]
        color (string|Color|bool) Color to print prompt string; can be
            ``False`` or ``None`` to print without color ["yellow"]
        yes_values (list[str]): Values user must type in to confirm
            [("y", "yes")]
        abort_on_unconfirmed (bool): If ``True``, print "Aborted" to
            stdout and exit with code 0 when not confirmed.
        abort_options (dict): Options to pass to :func:`abort` when not
            confirmed (these options will override any options set via
            ``abort_on_unconfirmed``)

    """
    prompt = prompt.format_map(config)
    prompt = '{prompt} [{yes_value}/N] '.format(prompt=prompt, yes_value=yes_values[0])

    if isinstance(yes_values, str):
        yes_values = (yes_values,)

    if color:
        prompt = printer.colorize(prompt, color=color)

    try:
        answer = input(prompt)
    except KeyboardInterrupt:
        print()
        confirmed = False
    else:
        answer = answer.strip().lower()
        confirmed = answer in yes_values

    if not confirmed and abort_on_unconfirmed:
        if abort_options is None:
            abort_options = {}

        abort_options.setdefault('code', 0)
        abort(**abort_options)

    return confirmed


def prompt(message, default=None, color=True):
    message = message.rstrip()
    if default is not None:
        default = default.rstrip()
        message = '%s [%s]' % (message, default)
    message = '%s ' % message
    if color is True:
        color = 'warning'
    if color:
        message = printer.colorize(message, color=color)
    try:
        value = input(message)
    except KeyboardInterrupt:
        print()
        abort()
    value = value.strip()
    if not value and default is not None:
        return default
    return value
