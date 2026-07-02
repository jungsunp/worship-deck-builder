"""ProPresenter protobuf bindings package.

The ``*_pb2`` modules here are generated from the vendored ``.proto`` snapshot by
``scripts/gen_proto.sh`` and are git-ignored (run that script after checkout;
needs ``protoc``). Only this hand-written ``__init__.py`` is committed.
The ``*_pb2`` modules are protoc's flat output and cross-import each other by
bare module name (``import cue_pb2``), so this directory must be importable
directly. Adding it to ``sys.path`` on package import makes those bare imports
resolve; then ``import presentation_pb2`` etc. work.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
