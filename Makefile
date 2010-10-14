VIRTUALENV = virtualenv
NOSE = bin/nosetests -s --with-xunit
TESTS = keyexchange/tests
PYTHON = bin/python
EZ = bin/easy_install
COVEROPTS = --cover-html --cover-html-dir=html --with-coverage --cover-package=keyexchange
COVERAGE = bin/coverage
PYLINT = bin/pylint
PKGS = keyexchange

.PHONY: all build test bench_one bench bend_report build_rpm hudson lint

all:	build

build:
	$(VIRTUALENV) --no-site-packages --distribute .
	$(PYTHON) setup.py develop
	$(EZ) nose
	$(EZ) WebTest
	$(EZ) Funkload
	$(EZ) pylint
	$(EZ) coverage

test:
	$(NOSE) $(TESTS)

bench_one:
	bin/fl-run-test keyexchange.tests.stress StressTest.test_session -u http://localhost:5000

bench:
	cd keyexchange/tests; ../../bin/fl-run-bench stress StressTest.test_session -u http://localhost:5000

bench_report:
	bin/fl-build-report --html -o html keyexchange/tests/stress-bench.xml

build_rpm:
	$(PYTHON) setup.py bdist_rpm

hudson:
	rm -f coverage.xml
	- $(COVERAGE) run --source=keyexchange $(NOSE) $(TESTS); $(COVERAGE) xml

lint:
	rm -f pylint.txt
	- $(PYLINT) -f parseable --rcfile=pylintrc $(PKGS) > pylint.txt

