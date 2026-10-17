"""Reproduce bundled CC BY-SA camera profiles; never reads/writes firmware.

Run from app/: python3 tools/rebuild_camera_profiles.py /tmp/new-profile-directory
Output goes to a new directory supplied as argv[1], not over existing data.
"""
import hashlib
import json
from pathlib import Path
import sys

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from darkslide.film_fit_import import convert_file


def main():
    output=Path(sys.argv[1]);output.mkdir(exist_ok=False)
    root=APP/"film_curves"
    manifest=json.loads((root/"camera_profiles_manifest.json").read_text())
    for entry in manifest["profiles"]:
        source=root/entry["source_file"]
        if hashlib.sha256(source.read_bytes()).hexdigest()!=entry["source_sha256"]:
            raise ValueError("source hash differs: "+entry["id"])
        profile=convert_file(source,entry["id"],entry["source_path"])
        profile["display_film"]=entry["film"];profile["print_stock"]=entry["print_stock"]
        profile["provenance"]["conversion_changes"]="Q13 ties-to-even/diagonal row repair; preserve all256 curves and post matrix; normalize schema and annotate origin"
        raw=(json.dumps(profile,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
        if hashlib.sha256(raw).hexdigest()!=entry["camera_sha256"]:
            raise ValueError("derived hash differs: "+entry["id"])
        (output/(entry["id"]+".json")).write_bytes(raw)
    print("reproduced",len(manifest["profiles"]),"profiles; all hashes match")


if __name__=="__main__":main()
