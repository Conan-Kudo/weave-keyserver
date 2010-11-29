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

.PHONY: all build test bench_one bench bend_report build_rpms hudson lint build_core

all:	build

build:
	$(VIRTUALENV) --no-site-packages --distribute .
	$(PYTHON) build.py
	$(PYTHON) setup.py develop
	$(EZ) nose
	$(EZ) WebTest
	$(EZ) Funkload
	$(EZ) pylint
	$(EZ) coverage
	$(EZ) pypi2rpm

test:
	$(NOSE) $(TESTS)

bench_one:
	bin/fl-run-test keyexchange.tests.stress StressTest.test_basic_usage -u http://localhost:5000

bench:
	cd keyexchange/tests; ../../bin/fl-run-bench stress StressTest.test_basic_usage -u http://localhost:5000

bench2_one:
	bin/fl-run-test keyexchange.tests.stress StressTest.test_DoS -u http://localhost:5000

bench2:
	cd keyexchange/tests; ../../bin/fl-run-bench stress StressTest.test_DoS -u http://localhost:5000

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
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms webob --version=1.0
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms paste --version=1.7.5.1
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms pastedeploy --version=1.3.4
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms pastescript --version=1.7.3
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms mako --version=0.3.4
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms markupsafe --version=0.11
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms beaker --version=1.5.4
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms python-memcached --version=1.45
	rm -rf build; $(PYTHON) setup.py --command-packages=pypi2rpm.command bdist_rpm2 --spec-file=KeyExchange.spec --dist-dir=$(CURDIR)/rpms --binary-only

build_core:
	cd deps/server-core; rm -rf build; ../../$(PYTHON) setup.py --command-packages=pypi2rpm.command bdist_rpm2 --spec-file=Services.spec --dist-dir=$(CURDIR)/rpms --binary-only
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms simplejson --version=2.1.1
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms routes --version=1.12.3
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms sqlalchemy --version=0.6.4
	$(PYPI2RPM) --dist-dir=$(CURDIR)/rpms mysql-python --version=1.2.3
