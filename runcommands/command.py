import argparse
import inspect
import json
import os
import time
from collections import OrderedDict

from .exc import RunCommandsError
from .util import Hide, cached_property, get_hr, printer


__all__ = ['DEFAULT_ENV', 'command']


DEFAULT_ENV = object()


class Command:

    """Command.
    
    Wraps a callable and provides a command line argument parser.
    
    Args:
        implementation (callable)
        name (str): Name of command as it will be called from the
            command line. Defaults to ``implementation.__name__`` (with
            underscores replaced with dashes).
        description (str): Description of command shown in command
            help. Defaults to ``implementation.__doc__``.
        help ({'arg name': 'help text'}): Help text for the command's
            args.
        type ({'arg name': 'type'}): Types used to parse values passed
            via the command line. May be any callable that accepts a
            single arg. Positional args will be strings unless specified
            here. Types for options are derived from keyword arg values
            by default.
        choices ({'arg name': list}): When given for an arg, the value
            for the arg must be one of the specified choices.
        env (str): Env to run command in. If this is specified, the
            command *will* be run in this env and may *only* be run in
            this env. If this is set to :global:`DEFAULT_ENV`, the
            command will be run in the env specified by the
            ``RUNCOMMANDS_DEFAULT_ENV`` environment variable.
        default_env (str): Default env to run command in. If this is
            specified, the command will be run in this env by default
            and may also be run in any other env. If this is set to
            :global:`DEFAULT_ENV`, the command will be run in the env
            specified by the ``RUNCOMMANDS_DEFAULT_ENV`` environment
            variable by default.
        config ({'dotted.name': value}): Additional or override config.
            This will supplement or override config read from other
            sources. Passed args take precedence over this config just
            like other config.
        timed (bool): Whether the command should be timed. Will print an
            info message showing how long the command took to complete
            when ``True``. Defaults to ``False``. 
    
    """

    def __init__(self, implementation, name=None, description=None, help=None, type=None,
                 choices=(), env=None, default_env=None, config=None, timed=False):
        if env is not None and default_env is not None:
            raise CommandError('Only one of `env` or `default_env` may be specified')

        if env is DEFAULT_ENV:
            env = os.environ['RUNCOMMANDS_DEFAULT_ENV']

        if default_env is DEFAULT_ENV:
            default_env = os.environ['RUNCOMMANDS_DEFAULT_ENV']

        self.implementation = implementation
        self.name = name if name is not None else implementation.__name__.replace('_', '-')
        self.description = description
        self.help_text = help or {}
        self.types = type or {}
        self.choices = choices or {}
        self.env = env
        self.default_env = default_env
        self.config = config or {}
        self.timed = timed
        self.qualified_name = '.'.join((implementation.__module__, implementation.__qualname__))
        self.defaults_path = '.'.join(('defaults', self.qualified_name))

    @classmethod
    def command(cls, name_or_wrapped=None, description=None, help=None, type=None, choices=None,
                env=None, default_env=None, config=None, timed=False):
        args = dict(
            description=description,
            help=help,
            type=type,
            choices=choices,
            env=env,
            default_env=default_env,
            config=config,
            timed=timed,
        )

        if callable(name_or_wrapped):
            wrapped = name_or_wrapped
            return Command(implementation=wrapped, **args)
        else:
            name = name_or_wrapped

        def wrapper(wrapped):
            return Command(implementation=wrapped, name=name, **args)

        return wrapper

    def get_run_env(self, specified_env):
        if self.env is True:
            # Command has no default env and requires one to be
            # specified.
            if specified_env is None:
                raise CommandError(
                    'The `{self.name}` command requires an env to be specified'
                    .format_map(locals()))
            return specified_env
        elif self.env:
            # Command may only be run in a designated env; make sure the
            # specified env matches that env.
            if specified_env and specified_env != self.env:
                raise CommandError(
                    'The `{self.name}` command may be run only in the "{self.env}" env but the '
                    '"{specified_env}" env was specified'.format_map(locals()))
            return self.env
        # If an env was specified, use that; otherwise fall back to the
        # default env for this command. The env may be None, which means
        # the command will be run in no env (which means it will have
        # access to only the default config).
        return specified_env or self.default_env

    def run(self, config, args):
        if self.timed:
            start_time = time.monotonic()

        kwargs = self.parse_args(config, args)
        result = self(config, **kwargs)

        if self.timed:
            hide = kwargs.get('hide', config._get_dotted('run.hide', 'none'))
            if not Hide.hide_stdout(hide):
                self.print_elapsed_time(time.monotonic() - start_time)

        return result

    def __call__(self, config, *args, **kwargs):
        if self.config:
            config = config._clone()
            config._update_dotted(self.config)

        if config.debug:
            printer.debug('Command called:', self.name)
            printer.debug('    Received positional args:', args)
            printer.debug('    Received keyword args:', kwargs)

        params = self.parameters
        defaults = config._get_dotted(self.defaults_path, None)

        if defaults:
            positionals = OrderedDict()
            for name, value in zip(self.positionals, args):
                positionals[name] = value

            for name in self.positionals:
                present = name in positionals or name in kwargs
                if not present and name in defaults:
                    kwargs[name] = defaults[name]

            for name in self.optionals:
                present = name in kwargs
                if not present and name in defaults:
                    kwargs[name] = defaults[name]

        def set_run_default(option):
            # If all of the following are true, the global default value
            # for the option will be injected into the options passed to
            # the command for this run:
            #
            # - This command defines the option.
            # - The option was not passed explicitly on this run.
            # - A global default is set for the option (it's not None).
            if option in params and option not in kwargs:
                global_default = config._get_dotted('run.%s' % option, None)
                if global_default is not None:
                    kwargs[option] = global_default

        set_run_default('echo')
        set_run_default('hide')

        if config.debug:
            printer.debug('Running command:', self.name)
            printer.debug('    Final positional args:', repr(args))
            printer.debug('    Final keyword args:', repr(kwargs))

        return self.implementation(config, *args, **kwargs)

    def parse_args(self, config, args):
        if config.debug:
            printer.debug('Parsing args for command `{self.name}`: {args}'.format(**locals()))
        parsed_args = self.get_arg_parser(config).parse_args(args)
        parsed_args = vars(parsed_args)
        return parsed_args

    def arg_names_for_param(self, param):
        params = self.parameters
        param = params[param] if isinstance(param, str) else param
        name = param.name

        if param.is_positional:
            return [name]

        arg_name = name.replace('_', '-')
        arg_name = arg_name.lower()
        arg_name = arg_name.strip('-')

        arg_names = []
        short_name = '-{arg_name[0]}'.format(arg_name=arg_name)
        long_name = '--{arg_name}'.format(arg_name=arg_name)

        first_char = name[0]

        names_that_start_with_first_char = [n for n in params if n.startswith(first_char)]

        # Ensure list is long enough to avoid IndexError
        if len(names_that_start_with_first_char) == 1:
            names_that_start_with_first_char.append(None)

        if first_char == 'e':
            # Ensure echo gets -E for consistency
            if 'echo' in params:
                names_that_start_with_first_char.remove('echo')
                names_that_start_with_first_char.insert(1, 'echo')

        if first_char == 'h':
            # -h is reserved for help
            names_that_start_with_first_char.insert(0, 'help')

            # Ensure hide gets -H for consistency
            if 'hide' in params:
                names_that_start_with_first_char.remove('hide')
                names_that_start_with_first_char.insert(1, 'hide')

        if names_that_start_with_first_char[0] == name:
            arg_names.append(short_name)
        elif names_that_start_with_first_char[1] == name:
            arg_names.append(short_name.upper())

        arg_names.append(long_name)

        if param.is_bool:
            if name == 'yes':
                no_long_name = '--no'
            elif name == 'no':
                no_long_name = '--yes'
            else:
                no_long_name = '--no-{name}'.format(name=arg_name)
            arg_names.append(no_long_name)

        return arg_names

    def print_elapsed_time(self, elapsed_time):
        m, s = divmod(elapsed_time, 60)
        m = int(m)
        hr = get_hr()
        msg = '{hr}\nElapsed time for {self.name} command: {m:d}m {s:.3f}s\n{hr}'
        msg = msg.format(**locals())
        printer.info(msg)

    @cached_property
    def signature(self):
        return inspect.signature(self.implementation)

    @cached_property
    def parameters(self):
        parameters = tuple(self.signature.parameters.items())[1:]
        params = OrderedDict()
        position = 1
        for name, param in parameters:
            if param.default is param.empty:
                param_position = position
                position += 1
            else:
                param_position = None
            params[name] = Parameter(param, param_position)
        return params

    @cached_property
    def positionals(self):
        parameters = self.parameters.items()
        return OrderedDict((n, p) for (n, p) in parameters if p.is_positional)

    @cached_property
    def optionals(self):
        parameters = self.parameters.items()
        return OrderedDict((n, p) for (n, p) in parameters if p.is_optional)

    @cached_property
    def arg_map(self):
        """Map command-line arg names to parameters."""
        arg_map = OrderedDict()
        for param in self.parameters.values():
            arg_names = self.arg_names_for_param(param)
            for arg_name in arg_names:
                arg_map[arg_name] = param
        help_param = HelpParameter()
        arg_map.setdefault('-h', help_param)
        arg_map.setdefault('--help', help_param)
        return arg_map

    @cached_property
    def param_map(self):
        """Map parameters to command-line arg names."""
        parameters = self.parameters.items()
        return OrderedDict((n, self.arg_names_for_param(p)) for (n, p) in parameters)

    def get_arg_parser(self, config=None):
        if self.description:
            description = self.description
        else:
            description = self.implementation.__doc__
            if description is not None:
                description = description.strip() or None
            if description is not None:
                lines = description.splitlines()
                title = lines[0]
                if title.endswith('.'):
                    title = title[:-1]
                lines = [title] + [line[4:] for line in lines[1:]]
                description = '\n'.join(lines)

        parser = argparse.ArgumentParser(
            prog=self.name,
            description=description,
            formatter_class=argparse.RawDescriptionHelpFormatter,
            argument_default=argparse.SUPPRESS,
        )

        defaults = config._get_dotted(self.defaults_path, {}) if config else {}

        for name, arg_names in self.param_map.items():
            param = self.parameters[name]

            if param.is_positional and name in defaults:
                default = defaults[name]
            else:
                default = param.default

            kwargs = {
                'help': self.help_text.get(name),
            }

            choices = self.choices.get(name)
            if choices:
                kwargs['choices'] = choices

            if name in self.types:
                kwargs['type'] = self.types[name]
            elif not param.is_bool and not param.is_dict and not param.is_list:
                for type_ in (int, float, complex):
                    if isinstance(default, type_):
                        kwargs['type'] = type_

            type_ = kwargs.get('type')

            is_dict_type = type_ is dict or type_ == 'dict' or param.is_dict

            if param.is_positional:
                # Make positionals optional if a default value is
                # specified via config.
                if default is not param.empty:
                    kwargs['nargs'] = '?'
                    kwargs['default'] = default
                parser.add_argument(*arg_names, **kwargs)
            else:
                kwargs['dest'] = name
                if isinstance(type_, bool_or):
                    # Allow --xyz or --xyz=<value>
                    true_or_value_kwargs = kwargs.copy()
                    true_or_value_kwargs['action'] = BoolOrAction
                    true_or_value_kwargs['nargs'] = '?'
                    true_or_value_arg_names = arg_names[:-1] if param.is_bool else arg_names
                    parser.add_argument(*true_or_value_arg_names, **true_or_value_kwargs)
                    if param.is_bool:
                        # Allow --no-xyz
                        false_kwargs = kwargs.copy()
                        false_kwargs.pop('choices', None)
                        false_kwargs.pop('type', None)
                        parser.add_argument(arg_names[-1], action='store_false', **false_kwargs)
                elif param.is_bool:
                    parser.add_argument(*arg_names[:-1], action='store_true', **kwargs)
                    parser.add_argument(arg_names[-1], action='store_false', **kwargs)
                elif is_dict_type:
                    kwargs['action'] = DictAddAction
                    kwargs.pop('type', None)
                    parser.add_argument(*arg_names, **kwargs)
                elif param.is_list:
                    kwargs['action'] = 'append'
                    parser.add_argument(*arg_names, **kwargs)
                else:
                    parser.add_argument(*arg_names, **kwargs)

        return parser

    @property
    def help(self):
        help_ = self.get_arg_parser().format_help()
        help_ = help_.split(': ', 1)[1]
        help_ = help_.strip()
        return help_

    @property
    def usage(self):
        usage = self.get_arg_parser().format_usage()
        usage = usage.split(': ', 1)[1]
        usage = usage.strip()
        return usage

    def __hash__(self):
        return hash(self.name)

    def __str__(self):
        return self.usage


command = Command.command


class Parameter:

    def __init__(self, parameter, position):
        default = parameter.default
        empty = parameter.empty
        self._parameter = parameter

        self.is_positional = default is empty
        self.is_optional = not self.is_positional

        self.is_bool = isinstance(default, bool)
        self.is_dict = isinstance(default, dict)
        self.is_list = isinstance(default, (list, tuple))

        self.position = position
        self.takes_value = self.is_positional or (self.is_optional and not self.is_bool)

    def __getattr__(self, name):
        return getattr(self._parameter, name)


class HelpParameter(Parameter):

    def __init__(self):
        self._parameter = None
        self.default = False
        self.is_positional = False
        self.is_optional = True
        self.is_bool = True
        self.is_dict = False
        self.is_list = False
        self.position = None
        self.takes_value = False


class BoolOr:

    """Used to indicate that an arg can be a flag or an option.
    
    Used like this::
    
        @command(type={'hide': bool_or(str)})
        def local(config, cmd, hide=False):
            "Run the specified command, possibly hiding its output."

    Allows for this::

        run local --hide all     # Hide everything
        run local --hide         # Hide everything with less effort
        run local --hide stdout  # Hide stdout only
        run local --no-hide      # Don't hide anything

    .. note:: The ``--no-<name>`` option will only be available when the
        default for the option is a bool.

    """

    def __init__(self, type_):
        self.type = type_

    def __call__(self, value):
        return self.type(value)


bool_or = BoolOr


class BoolOrAction(argparse.Action):

    def __call__(self, parser, namespace, value, option_string=None):
        if value is None:
            value = True
        setattr(namespace, self.dest, value)


class DictAddAction(argparse.Action):

    def __call__(self, parser, namespace, item, option_string=None):
        if not hasattr(namespace, self.dest):
            setattr(namespace, self.dest, OrderedDict())

        items = getattr(namespace, self.dest)

        try:
            name, value = item.split('=', 1)
        except ValueError:
            raise ValueError('Expected name=<json value> or name=<str value>') from None

        if not value:
            value = 'null'

        try:
            value = json.loads(value)
        except ValueError:
            pass

        items[name] = value


class CommandError(RunCommandsError):

    pass
