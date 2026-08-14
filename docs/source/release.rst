Release Process
===============

Since v0.1.0, every official release is managed by
:file:`scripts/release.py` — you do not need to edit the version number,
CHANGELOG, tags, or documentation version by hand.

Single source of truth for the version
--------------------------------------

The :file:`VERSION` file at the repository root is the single source of truth
for the version number:

.. code-block:: bash

   echo "0.1.0" > VERSION

It is read from:

* The Sphinx documentation (:file:`docs/source/conf.py` reads
  :file:`VERSION`);
* The release script (:file:`scripts/release.py` reads and writes
  :file:`VERSION`);
* The version displayed at the top of the documentation.

Running a release
-----------------

.. code-block:: bash

   python3 scripts/release.py patch   # 0.1.0 → 0.1.1
   python3 scripts/release.py minor   # 0.1.1 → 0.2.0
   python3 scripts/release.py major   # 0.2.0 → 1.0.0

The script will, in order:

1. Check that the Git working tree is clean (aborts if there are uncommitted
   changes);
2. Read the previous Git tag and collect the commits / diff since the last
   release;
3. Bump :file:`VERSION` according to the ``patch / minor / major`` rule;
4. Promote the ``[Unreleased]`` entries in :file:`CHANGELOG.md` to a
   versioned section;
5. Run the tests (when ``pytest`` / a test directory exists);
6. Build the Sphinx documentation once locally to confirm there are no
   errors;
7. Create a Git commit (including VERSION / CHANGELOG / documentation
   changes);
8. Create a Git tag (for example ``v0.1.1``).

**The script never pushes automatically.** When it finishes it prompts:

.. code-block:: text

   Release v0.1.1 ready.
   Push to remote?

Push manually only after you have confirmed you want to publish.

Version numbering
-----------------

.. list-table::
   :header-rows: 1
   :widths: 15 25 60

   * - Command
     - Example
     - When to use
   * - ``patch``
     - ``0.1.0 → 0.1.1``
     - Bug fixes and small changes
   * - ``minor``
     - ``0.1.1 → 0.2.0``
     - New features (backwards compatible)
   * - ``major``
     - ``0.2.0 → 1.0.0``
     - Breaking changes / milestones

Recovering the previous stable version
--------------------------------------

Every version has a Git tag, so you can always roll back:

.. code-block:: bash

   git tag                        # list all versions
   git checkout v0.1.0            # check out a previous stable version (or git switch -c hotfix v0.1.0)
