%define name python-keyexchange
%define pythonname KeyExchange
%define version 0.1
%define unmangled_version 0.1
%define unmangled_version 0.1
%define release 1

Summary: Key Exchange server
Name: %{name}
Version: %{version}
Release: %{release}
Source0: %{pythonname}-%{unmangled_version}.tar.gz
License: MPL
Group: Development/Libraries
BuildRoot: %{_tmppath}/%{pythonname}-%{version}-%{release}-buildroot
Prefix: %{_prefix}
BuildArch: noarch
Vendor: Tarek Ziade <tarek@mozilla.com>
Requires: httpd memcached mod_wsgi python26 pylibmc python26-setuptools python-webob python-meld3 python-paste python-pastedeploy python-pastescript python-repoze-profile

Url: https://hg.mozilla.org/services/server-key-exchange

%description
===================
Key Exchange Server
===================

Implementation of a key exchange server that can be used with protocols like
J-PAKE.

See: https://wiki.mozilla.org/Services/Sync/SyncKey/J-PAKE


%prep
%setup -n %{pythonname}-%{unmangled_version} -n %{pythonname}-%{unmangled_version}

%build
python2.6 setup.py build

%install
mkdir -p %{buildroot}%{_sysconfdir}/keyexchange
install -m 0644 etc/keyexchange.wsgi %{buildroot}%{_sysconfdir}/keyexchange/keyexchange.wsgi
install -m 0644 etc/production.ini %{buildroot}%{_sysconfdir}/keyexchange/production.ini
mkdir -p %{buildroot}%{_sysconfdir}/httpd
mkdir -p %{buildroot}%{_sysconfdir}/httpd/conf.d
install -m 0644 etc/keyexchange.apache.conf %{buildroot}%{_sysconfdir}/httpd/conf.d/keyexchange.conf
mkdir -p %{buildroot}%{_localstatedir}/log
touch %{buildroot}%{_localstatedir}/log/keyexchange.log
python2.6 setup.py install --single-version-externally-managed --root=$RPM_BUILD_ROOT --record=INSTALLED_FILES

%clean
rm -rf $RPM_BUILD_ROOT

%post
touch %{_localstatedir}/log/keyexchange.log
chown apache:apache %{_localstatedir}/log/keyexchange.log
chmod 750 %{_localstatedir}/log/keyexchange.log

%files -f INSTALLED_FILES

%attr(750, apache, apache) %ghost %{_localstatedir}/log/keyexchange.log

%dir %{_sysconfdir}/keyexchange/

%config(noreplace) %{_sysconfdir}/keyexchange/*

%config(noreplace) %{_sysconfdir}/httpd/conf.d/keyexchange.conf

%defattr(-,root,root)
