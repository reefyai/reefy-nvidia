# Registry tool transfer regression

The publication workflow downloads each registry tool into a private temporary
file before installing either tool. Native curl retries are limited to two
retries, including interrupted transfers and TLS read failures. Partial output
is removed on exhaustion. HTTPS certificate verification remains enabled.
Downloads no longer stream directly into the archive extractor.

Run the complete established tests with:

```sh
python3 -m unittest discover -s tests -v
```

`test_registry_tool_download.py` runs real curl against a synthetic local HTTP
server. A truncated first response must recover with exactly two requests and
no duplicated bytes. Repeated truncation must fail after exactly three requests
and leave no partial output. This models interrupted transfer handling, not the
root cause of any external TLS failure. Artifact signatures and payload checks
remain part of the full publication workflow.

The identical tests fail twice against workflow source `cd097619e8f01ea723a5c6901bb1cea968341e9f`
and pass twice against the fixed workflow. To reproduce the baseline without
changing the working workflow, run from this repository:

```python
import subprocess, sys, unittest
suite = unittest.defaultTestLoader.discover(
    'tests', pattern='test_registry_tool_download.py')
sys.modules['test_registry_tool_download'].WORKFLOW = subprocess.check_output(
    ['git', 'show', 'cd097619e8f01ea723a5c6901bb1cea968341e9f:.github/workflows/publish.yml'], text=True)
unittest.TextTestRunner(verbosity=2).run(suite)
```
