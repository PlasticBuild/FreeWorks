# SPDX-License-Identifier: LGPL-2.1-or-later
""

# extapps/65: at release time the modules are packed into one file (modules.fwbundle), read from there for a faster cold
# start; without that file (a development setup) Python imports the folder as always
from . import bundle as _bundle
_bundle.install(__name__, __path__[0])
