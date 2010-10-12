VIRTUALENV = virtualenv
NOSE = bin/nosetests -s
TESTS = keyexchange/tests
PYTHON = bin/python
EZ = bin/easy_install

.PHONY: all build test bench_one bench bend_report build_rpm

all:	build

build:
	$(VIRTUALENV) --no-site-packages --distribute .
	$(PYTHON) setup.py develop
	$(EZ) nose
	$(EZ) WebTest
	$(EZ) Funkload

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
