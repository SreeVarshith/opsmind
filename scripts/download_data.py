"""Download the public datasets OpsMind learns from into data/raw/.

    python scripts/download_data.py

Sources (all public, open licenses):
  - Prometheus Operator runbooks: real on-call runbooks for Kubernetes alerts
  - danluu/post-mortems: a curated list of public incident postmortems
  - logpai/loghub: 2k-line log samples from real systems, with parsed event templates
"""
import io
import tarfile
from pathlib import Path

import httpx

RAW = Path("data/raw")

RUNBOOKS_TARBALL = "https://codeload.github.com/prometheus-operator/runbooks/tar.gz/refs/heads/main"
POSTMORTEMS_README = "https://raw.githubusercontent.com/danluu/post-mortems/master/README.md"
LOGHUB_SYSTEMS = ["HDFS", "Hadoop", "Spark", "Zookeeper", "OpenStack", "Linux", "OpenSSH", "Apache"]
LOGHUB_URL = "https://raw.githubusercontent.com/logpai/loghub/master/{s}/{s}_2k.log_structured.csv"


def download_runbooks(client: httpx.Client) -> int:
    out = RAW / "runbooks"
    out.mkdir(parents=True, exist_ok=True)
    data = client.get(RUNBOOKS_TARBALL).raise_for_status().content
    count = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            # Only take the markdown runbooks; never extract anything else from the archive.
            if not (member.isfile() and "/content/runbooks/" in member.name and member.name.endswith(".md")):
                continue
            parts = member.name.split("/content/runbooks/")[1].split("/")
            if parts[-1] == "_index.md":
                continue
            target = out / "__".join(parts)  # e.g. kubernetes__KubePodCrashLooping.md
            target.write_bytes(tar.extractfile(member).read())
            count += 1
    return count


def download_postmortems(client: httpx.Client) -> int:
    out = RAW / "postmortems"
    out.mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_bytes(client.get(POSTMORTEMS_README).raise_for_status().content)
    return 1


def download_logs(client: httpx.Client) -> int:
    out = RAW / "logs"
    out.mkdir(parents=True, exist_ok=True)
    for s in LOGHUB_SYSTEMS:
        (out / f"{s}.csv").write_bytes(client.get(LOGHUB_URL.format(s=s)).raise_for_status().content)
    return len(LOGHUB_SYSTEMS)


if __name__ == "__main__":
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        print(f"runbooks:    {download_runbooks(client)} files")
        print(f"postmortems: {download_postmortems(client)} file")
        print(f"logs:        {download_logs(client)} systems")
    print("Done. Data is in data/raw/")
