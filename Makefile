venv ?= .env
python_version ?= 3

pip := $(venv)/bin/pip
python := $(venv)/bin/python

remote_user ?= `whoami`
remote_host="$(remote_user)@rc.pdx.edu"


init: $(venv)
	$(pip) install -r requirements.txt
	$(python) -m unittest discover .

$(venv):
	@if [ -e virtualenv ]; then \
            virtualenv -p $(python_version) $(venv); \
        else \
            python$(python_version) -m venv $(venv); \
        fi

reinit: clean-all init

# TODO: We can use: RTD, GitHub pages (rendered in repo) or configure
#       an S3 bucket to host project docs.
documentation: init  ## Builds the currently available documentation.
	@. $(venv)/bin/activate; sphinx-build docs/source docs/

clean:
	find . -name __pycache__ -type d -print0 | xargs -0 rm -r
clean-all: clean-build clean-dist clean-venv
clean-build:
	rm -rf build
clean-dist:
	rm -rf dist
clean-venv:
	rm -rf $(venv)

# upload_dist: clean clean-build clean-dist
upload_dist: clean-build clean-dist
	$(venv)/bin/python setup.py bdist_wheel --universal
	@for archive in `ls dist`; do \
            scp dist/$${archive} $(remote_host):/tmp/; \
            ssh $(remote_host) chgrp arc /tmp/$${archive}; \
            ssh $(remote_host) sg arc -c "\"mv /tmp/$${archive} /vol/www/cdn/pypi/dist/\""; \
        done

.PHONY = init reinit clean clean-all clean-venv upload_dist
