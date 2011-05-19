APPNAME = server-key-exchange
DEPS = server-core
VIRTUALENV = virtualenv
NOSE = bin/nosetests -s --with-xunit
TESTS = keyexchange/tests
PYTHON = bin/python
EZ = bin/easy_install
COVEROPTS = --cover-html --cover-html-dir=html --with-coverage --cover-package=keyexchange
COVERAGE = bin/coverage
PYLINT = bin/pylint
PKGS = keyexchange
PYPI2RPM = bin/pypi2rpm.py

.PHONY: all build test bench_one bench bend_report build_rpms hudson lint functest

all:	build

build:
	$(VIRTUALENV) --no-site-packages --distribute .
	$(PYTHON) build.py $(APPNAME) $(DEPS)
	$(EZ) nose
	$(EZ) WebTest
	$(EZ) Funkload
	$(EZ) pylint
	$(EZ) coverage
	$(EZ) pypi2rpm
	$(EZ) wsgi_intercept
	$(EZ) wsgiproxy

test:
	$(NOSE) $(TESTS)

bench_one:
	cd keyexchange/tests; ../../bin/fl-run-test keyexchange.tests.stress StressTest.test_channel_put_get

bench:
	cd keyexchange/tests; ../../bin/fl-run-bench stress StressTest.test_channel_put_get

bench2_one:
	bin/fl-run-test keyexchange.tests.stress StressTest.test_DoS -

bench2:
	cd keyexchange/tests; ../../bin/fl-run-bench stress StressTest.test_DoS

bench3_one:
	cd keyexchange/tests; ../../bin/fl-run-test keyexchange.tests.stress StressTest.test_full_protocol

bench3:
	cd keyexchange/tests; ../../bin/fl-run-bench stress StressTest.test_full_protocol

bench_report:
	bin/fl-build-report --html -o html keyexchange/tests/stress-bench.xml

hudson:
	rm -f coverage.xml
	- $(COVERAGE) run --source=keyexchange $(NOSE) $(TESTS); $(COVERAGE) xml

lint:
	rm -f pylint.txt
	- $(PYLINT) -f parseable --rcfile=pylintrc $(PKGS) > pylint.txt

build_rpms:
	rm -rf $(CURDIR)/rpms
	mkdir $(CURDIR)/rpms
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms cef
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms webob --version=1.0
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms paste --version=1.7.5.1
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms pastedeploy --version=1.3.4
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms pastescript --version=1.7.3
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms mako --version=0.3.4
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms markupsafe --version=0.11
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms beaker --version=1.5.4
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms python-memcached --version=1.45
	rm -rf build; $(PYTHON) setup.py --command-packages=pypi2rpm.command bdist_rpm2 --spec-file=KeyExchange.spec --dist-dir=$(CURDIR)/rpms --binary-only
	cd deps/server-core; rm -rf build; ../../$(PYTHON) setup.py --command-packages=pypi2rpm.command bdist_rpm2 --spec-file=Services.spec --dist-dir=$(CURDIR)/rpms --binary-only
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms simplejson --version=2.1.1
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms routes --version=1.12.3
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms sqlalchemy --version=0.6.6
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms mysql-python --version=1.2.3
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms wsgiproxy --version=0.2.2

mach: build build_rpms
	mach clean
	mach yum install python26 python26-setuptools
	cd rpms; wget http://mrepo/mrepo/5-x86_64/RPMS.mozilla-services/gunicorn-0.11.2-1moz.x86_64.rpm
	cd rpms; wget http://mrepo/mrepo/5-x86_64/RPMS.mozilla/nginx-0.7.65-4.x86_64.rpm
	mach yum install rpms/*
	mach chroot python2.6 -m keyexchange.run
