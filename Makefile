APPNAME = server-key-exchange
DEPS = server-core
VIRTUALENV = virtualenv
NOSE = bin/nosetests -s --with-xunit
TESTS = keyexchange/tests
PYTHON = bin/python
COVEROPTS = --cover-html --cover-html-dir=html --with-coverage --cover-package=keyexchange
COVERAGE = bin/coverage
PYLINT = bin/pylint
PKGS = keyexchange
BUILDAPP = bin/buildapp
BUILDRPMS = bin/buildrpms
BUILD_TMP = /tmp/server-key-exhange-build.${USER}
PYPI = http://pypi.python.org/simple
PYPI2RPM = bin/pypi2rpm.py --index=$(PYPI)
PYPIOPTIONS = -i $(PYPI)
CHANNEL = dev
RPM_CHANNEL = prod
INSTALL = bin/pip install
INSTALLOPTIONS = -U -i $(PYPI)
PYPI2RPM = bin/pypi2rpm.py --index=$(PYPI)
PYPIOPTIONS = -i $(PYPI)
EZ = bin/easy_install
EZOPTIONS = -U -i $(PYPI)
BENCH_CYCLE = 10
BENCH_DURATION = 10
BENCH_SCP =

ifdef TEST_REMOTE
	BENCHOPTIONS = --url $(TEST_REMOTE) --cycle $(BENCH_CYCLE) --duration $(BENCH_DURATION)
else
	BENCHOPTIONS = --cycle $(BENCH_CYCLE) --duration $(BENCH_DURATION)
endif

ifdef PYPIEXTRAS
	PYPIOPTIONS += -e $(PYPIEXTRAS)
	INSTALLOPTIONS += -f $(PYPIEXTRAS)
endif


ifdef PYPISTRICT
	PYPIOPTIONS += -s
	ifdef PYPIEXTRAS
		HOST = `python -c "import urlparse; print urlparse.urlparse('$(PYPI)')[1] + ',' + urlparse.urlparse('$(PYPIEXTRAS)')[1]"`

	else
		HOST = `python -c "import urlparse; print urlparse.urlparse('$(PYPI)')[1]"`
	endif

endif

INSTALL += $(INSTALLOPTIONS)


.PHONY: all build test bench_one bench bend_report build_rpms hudson lint functest

all:	build

build:
	$(VIRTUALENV) --no-site-packages --distribute .
	$(INSTALL) Distribute
	$(INSTALL) MoPyTools
	$(INSTALL) nose
	$(INSTALL) WebTest
	$(INSTALL) coverage
	$(BUILDAPP) -c $(CHANNEL) $(PYPIOPTIONS) $(DEPS)
	# py-scrypt doesn't play nicely with pypi2rpm
	# so we can't list it in the requirements files.
	mkdir -p ${BUILD_TMP}
	cd ${BUILD_TMP}; tar -xzvf $(CURDIR)/upstream-deps/py-scrypt-0.6.0.tar.gz
	$(INSTALL) ${BUILD_TMP}
	rm -rf ${BUILD_TMP}
	# Pre-compile mako templates into the correct directories.
	for TMPL in `find . -name '*.mako'`; do ./bin/python -c "from mako.template import Template; Template(filename='$$TMPL', module_directory='`dirname $$TMPL`', uri='`basename $$TMPL`')"; done;


update:
	$(BUILDAPP) -c $(CHANNEL) $(PYPIOPTIONS) $(DEPS)
	# Pre-compile mako templates into the correct directories.
	for TMPL in `find . -name '*.mako'`; do ./bin/python -c "from mako.template import Template; Template(filename='$$TMPL', module_directory='`dirname $$TMPL`', uri='`basename $$TMPL`')"; done;

test:
	$(NOSE) $(TESTS)

bench_one:
	cd keyexchange/tests; ../../bin/fl-run-test keyexchange.tests.stress StressTest.test_channel_put_get

bench:
	- cd keyexchange/tests; ../../bin/fl-run-bench $(BENCHOPTIONS) stress StressTest.test_channel_put_get
	$(BENCH_SCP)

bench_report:
	bin/fl-build-report --html -o html keyexchange/tests/keyexchange.xml

hudson:
	rm -f coverage.xml
	- $(COVERAGE) run --source=keyexchange $(NOSE) $(TESTS); $(COVERAGE) xml

lint:
	rm -f pylint.txt
	- $(PYLINT) -f parseable --rcfile=pylintrc $(PKGS) > pylint.txt

build_rpms:
	rm -rf rpms
	mkdir -p ${BUILD_TMP}
	$(BUILDRPMS) -c $(RPM_CHANNEL) $(PYPIOPTIONS) $(DEPS)
	# py-scrypt doesn't play nicely with pypi2rpm.
	cd ${BUILD_TMP}; tar -xzvf $(CURDIR)/upstream-deps/py-scrypt-0.6.0.tar.gz
	cd ${BUILD_TMP}; python setup.py  --command-packages=pypi2rpm.command bdist_rpm2 --binary-only --name=python26-scrypt --dist-dir=$(CURDIR)/rpms

mach: build build_rpms
	mach clean
	mach yum install python26 python26-setuptools
	cd rpms; wget http://mrepo.mozilla.org/mrepo/5-x86_64/RPMS.mozilla-services/gunicorn-0.11.2-1moz.x86_64.rpm
	cd rpms; wget http://mrepo.mozilla.org/mrepo/5-x86_64/RPMS.mozilla/nginx-0.7.65-4.x86_64.rpm
	mach yum install rpms/*
	mach chroot python2.6 -m keyexchange.run

mock: build build_rpms
	mock init
	mock --install python26 python26-setuptools
	cd rpms; wget http://mrepo.mozilla.org/mrepo/5-x86_64/RPMS.mozilla-services/gunicorn-0.11.2-1moz.x86_64.rpm
	cd rpms; wget http://mrepo.mozilla.org/mrepo/5-x86_64/RPMS.mozilla/nginx-0.7.65-4.x86_64.rpm
	mock --install rpms/*
	mock --chroot "python2.6 -m keyexchange.run"
