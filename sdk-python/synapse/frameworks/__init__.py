"""Framework-specific install hooks for ``synapse.install(framework=...)``.

Each module here registers itself on import via
``synapse.install.register_framework(name, install_fn)``.

Lazy-loaded — these modules are only imported when the user calls
``synapse.install()`` with the matching framework name. They tolerate
the framework not being installed (the install_fn no-ops + logs).
"""
