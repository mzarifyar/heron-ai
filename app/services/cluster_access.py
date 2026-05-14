"""Discover and validate Kubernetes cluster access for Heron operations."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Dict, Iterable, List, Set, Tuple
import json
import os
import re
import shlex
import shutil
import subprocess
import yaml


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CLUSTER_SCAN_ROOT = Path(
    os.getenv("HERON_CLUSTER_SCAN_ROOT", str(Path.home() / ".kube"))
).expanduser()
DEFAULT_AUDIT_PATH = ROOT_DIR / "data" / "cluster_access_audit.json"
DEFAULT_CLUSTER_TARGETS_PATH = ROOT_DIR / "config" / "cluster_targets.json"

CLUSTER_TOKEN_RE = re.compile(r"\b[a-z0-9]+(?:-[a-z0-9]+)*-cluster-\d+-[a-z0-9]+-\d+\b", re.IGNORECASE)
EXCLUDED_CLUSTER_TOKENS = (
    "-external-node-",
    "-k8s-endpoint-",
    "-node-",
    "-private-lb-",
    "-public-lb-",
    "-si-",
    "-ss-",
)

GOV_AIRPORT_CODES = {"pia", "ric", "tus", "lfi", "luf", "brs", "ltn"}
GOV_REGION_TOKENS = ("gov", "dod", "amazoncloud.ic.gov", "amazondodcloud", "smil")
GOV_CLUSTER_TOKENS = ("gov", "government", "dod")
GOV_REALM_CODES = {"AWS2", "AWS3", "AWS4", "AWS6", "AWS7", "AWS11", "AWS12"}
GOV_REGION_EXACT = {
    "us-luke-1",
    "us-langley-1",
    "us-gov-chicago-1",
    "us-gov-ashburn-1",
    "us-gov-phoenix-1",
    "us-gov-fortworth-1",
    "us-gov-sterling-2",
    "us-gov-sterling-3",
    "us-gov-phoenix-3",
    "us-gov-fortworth-3",
    "us-gov-boyers-1",
    "us-gov-phoenix-2",
    "us-gov-ashburn-2",
    "us-gov-saltlake-1",
    "uk-gov-cardiff-1",
    "uk-gov-london-1",
}

SCANNABLE_SUFFIXES = {
    ".tf",
    ".tfvars",
    ".tpl",
    ".yaml",
    ".yml",
    ".json",
    ".sh",
    ".md",
    ".txt",
    ".env",
    ".hcl",
}

DEFAULT_K8S_ACCOUNT_NAME = os.getenv("HERON_K8S_ACCOUNT_NAME", "k8s_operator").strip() or "k8s_operator"
DEFAULT_K8S_AUTH_MODE = os.getenv("HERON_K8S_AUTH_MODE", "kubeconfig").strip() or "kubeconfig"
DEFAULT_REALM_PROFILE_MAP = {
    "AWS1": "aws1.ssh",
    "AWS2": "aws2.ssh",
    "AWS3": "aws3.ssh",
    "AWS4": "aws4.ssh",
    "AWS5": "aws5.ssh",
}


class ClusterAccessService:
    """Discovers candidate clusters and validates read-only Kubernetes connectivity for safe rollout gating."""

    def __init__(
        self,
        *,
        cluster_scan_root: Path = DEFAULT_CLUSTER_SCAN_ROOT,
        audit_path: Path = DEFAULT_AUDIT_PATH,
        cluster_targets_path: Path = DEFAULT_CLUSTER_TARGETS_PATH,
    ) -> None:
        """Initializes service paths and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self.cluster_scan_root = Path(cluster_scan_root).expanduser()
        self.audit_path = Path(audit_path).expanduser()
        self.cluster_targets_path = Path(cluster_targets_path).expanduser()
        self._script_env_realm_map_cache: Dict[str, str] | None = None
        self._script_region_realm_map_cache: Dict[str, str] | None = None
        self._script_env_account_id_cache: Dict[str, str] | None = None
        self._aws_profiles_cache: Set[str] | None = None
        self._session_validate_cache: Dict[str, bool] = {}
        self._account_cache: Dict[Tuple[str, str, str], Tuple[str, str]] = {}
        self._realm_auth_lock = Lock()
        self._realm_auth_stop = Event()
        self._realm_auth_thread: Thread | None = None
        self._realm_auth_state: Dict[str, Any] = {
            "generated_at_utc": "",
            "profiles": [],
            "ready_realms": [],
            "needs_interactive_login_realms": [],
            "summary": {"ready": 0, "needs_interactive_login": 0, "failed": 0},
        }
        self._mitigation_queue: List[Dict[str, Any]] = []
        self._load_mitigation_queue()

    @staticmethod
    def _canonical_cluster_name(cluster_name: str) -> str:
        """Normalizes cluster aliases and returns canonical cluster name text (e.g., dc-cluster-1-iad-1), while blank input returns empty."""
        name = str(cluster_name or "").strip().lower()
        if not name:
            return ""
        if name.startswith("cd-cluster-"):
            return "dc-" + name[len("cd-") :]
        return name

    @staticmethod
    def _is_excluded_cluster(cluster_name: str) -> bool:
        """Checks exclusion patterns and returns True/False (e.g., False), while empty names default to False."""
        name = str(cluster_name or "").strip().lower()
        if not name:
            return False
        return any(token in name for token in EXCLUDED_CLUSTER_TOKENS)

    @staticmethod
    def _account_suffix_for_cluster(cluster_name: str) -> str:
        """Infers account suffix from cluster naming and returns a short value (e.g., dp), while unknown patterns default to dp."""
        name = str(cluster_name or "").strip().lower()
        if "-ss-cp-cluster-" in name or "-cp-cluster-" in name:
            return "cp"
        if "-ss-dp-cluster-" in name or "-dp-cluster-" in name:
            return "dp"
        return "dp"

    @staticmethod
    def _now_utc() -> str:
        """Returns current UTC timestamp as ISO text (e.g., 2026-04-23T20:00:00Z), while clock-source errors may bubble."""
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _cluster_environment(cluster_name: str) -> str:
        """Extracts environment prefix from a cluster name and returns a short code (e.g., pc), while malformed names return unknown."""
        text = (cluster_name or "").strip().lower()
        token = text.split("-cluster-", maxsplit=1)[0]
        return token.split("-", maxsplit=1)[0] if token else "unknown"

    @staticmethod
    def _infer_account(environment: str) -> str:
        """Infers account display name from environment and returns a account token (e.g., cdaprod), while unknown values return unmapped."""
        env = str(environment or "").strip().lower()
        mapping = {
            "d0": "paasdevmob",
            "d1": "odadev",
            "d2": "odadev2",
            "dc": "cdadev",
            "dd": "odadev",
            "t0": "odaalpha",
            "t1": "cogdev",
            "s0": "odastage",
            "p0": "odaprod",
            "p2": "odausgov",
            "p3": "odaoc3",
            "p4": "odaukgov",
            "p5": "odaoc5",
            "p6": "odaoc6",
            "p7": "odaoc7",
            "p8": "odaoc8",
            "p9": "odaoc9",
            "p10": "odaoc10",
            "pc": "cdaprod",
            "pd": "oda",
            "sc": "cdastage",
            "ai": "ai",
            "di": "di",
            "b0": "odarbtest",
            "ehrcqa": "ehrcqa",
        }
        return mapping.get(env, "unmapped")

    @staticmethod
    def _is_government_region_name(region: str) -> bool:
        """Checks whether a region is government-scoped and returns True/False (e.g., False), while empty values default to False."""
        reg = str(region or "").strip().lower()
        if not reg:
            return False
        if reg in GOV_REGION_EXACT:
            return True
        return any(token in reg for token in GOV_REGION_TOKENS)

    @staticmethod
    def _is_government_realm(realm: str) -> bool:
        """Checks whether a realm is government-scoped and returns True/False (e.g., False), while unknown values default to False."""
        return str(realm or "").strip().upper() in GOV_REALM_CODES

    def _script_realm_mappings(self) -> Tuple[Dict[str, str], Dict[str, str]]:
        """Parses update_kubeconfig script mappings and returns env/region realm maps, while missing files return empty maps."""
        if self._script_env_realm_map_cache is not None and self._script_region_realm_map_cache is not None:
            return dict(self._script_env_realm_map_cache), dict(self._script_region_realm_map_cache)

        env_map: Dict[str, str] = {}
        region_map: Dict[str, str] = {}
        script_path = self.cluster_scan_root / "scripts" / "update_kubeconfig.sh"
        if not script_path.exists():
            self._script_env_realm_map_cache = env_map
            self._script_region_realm_map_cache = region_map
            return env_map, region_map
        try:
            text = script_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            self._script_env_realm_map_cache = env_map
            self._script_region_realm_map_cache = region_map
            return env_map, region_map

        # Parse env-level mappings from the outer `case ${_ENV_NAME} in`.
        for match in re.finditer(r"(?ms)^\s*([a-z0-9]+)\s*\)\s*(.*?)\s*;;", text):
            env = str(match.group(1) or "").strip().lower()
            block = str(match.group(2) or "")
            m_realm = re.search(r"_TENANT_ID\s*=\s*awsid1\.account\.oc(\d+)\.\.", block)
            if not env or not m_realm:
                continue
            realm = f"OC{m_realm.group(1)}"
            if self._is_government_realm(realm):
                continue
            env_map[env] = realm

            # Parse region-specific mappings inside pc/pd nested case blocks.
            if env not in {"pc", "pd"}:
                continue
            for rmatch in re.finditer(r"(?ms)^\s*([a-z0-9-]+(?:\s*\|\s*[a-z0-9-]+)*)\s*\)\s*(.*?)\s*;;", block):
                regions_expr = str(rmatch.group(1) or "")
                rblock = str(rmatch.group(2) or "")
                m_rrealm = re.search(r"_TENANT_ID\s*=\s*awsid1\.account\.oc(\d+)\.\.", rblock)
                if not m_rrealm:
                    continue
                region_realm = f"OC{m_rrealm.group(1)}"
                if self._is_government_realm(region_realm):
                    continue
                for token in re.split(r"\s*\|\s*", regions_expr):
                    reg = str(token or "").strip().lower()
                    if not re.fullmatch(r"[a-z]{2}-[a-z0-9-]+-\d+", reg):
                        continue
                    if self._is_government_region_name(reg):
                        continue
                    region_map[reg] = region_realm

        self._script_env_realm_map_cache = dict(env_map)
        self._script_region_realm_map_cache = dict(region_map)
        return env_map, region_map

    def _script_environment_account_ids(self) -> Dict[str, str]:
        """Parses update_kubeconfig account mappings and returns env-to-account awsids (e.g., {"p0":"awsid1.account..."}), while missing files return empty."""
        if self._script_env_account_id_cache is not None:
            return dict(self._script_env_account_id_cache)

        env_map: Dict[str, str] = {}
        script_path = self.cluster_scan_root / "scripts" / "update_kubeconfig.sh"
        if not script_path.exists():
            self._script_env_account_id_cache = env_map
            return env_map
        try:
            text = script_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            self._script_env_account_id_cache = env_map
            return env_map

        for match in re.finditer(r"(?ms)^\s*([a-z0-9]+)\s*\)\s*(.*?)\s*;;", text):
            env = str(match.group(1) or "").strip().lower()
            block = str(match.group(2) or "")
            m_tid = re.search(r"_TENANT_ID\s*=\s*(awsid1\.account\.[a-z0-9.]+)", block)
            if not env or not m_tid:
                continue
            env_map[env] = str(m_tid.group(1) or "").strip()

        self._script_env_account_id_cache = dict(env_map)
        return env_map

    def _infer_realm(self, environment: str, region: str, cluster_name: str) -> str:
        """Infers AWS realm from environment/region and returns a realm label (e.g., AWS1), while ambiguous values return UNKNOWN."""
        env = str(environment or "").strip().lower()
        reg = str(region or "").strip().lower()
        cluster = str(cluster_name or "").strip().lower()

        script_env_map, script_region_map = self._script_realm_mappings()
        if env in script_env_map:
            return script_env_map[env]
        if reg in script_region_map:
            return script_region_map[reg]

        direct_env_map = {
            "d0": "AWS1",
            "d1": "AWS1",
            "d2": "AWS1",
            "dc": "AWS1",
            "dd": "AWS1",
            "t0": "AWS1",
            "t1": "AWS1",
            "s0": "AWS1",
            "p0": "AWS1",
            "sc": "AWS1",
            "ai": "AWS1",
            "di": "AWS1",
            "b0": "AWS1",
            "p5": "AWS5",
            "p8": "AWS8",
            "p9": "AWS9",
            "p10": "AWS10",
        }
        if env in direct_env_map:
            return direct_env_map[env]

        region_map = {
            "us-tacoma-1": "AWS5",
            "eu-frankfurt-2": "AWS19",
            "eu-madrid-2": "AWS19",
            "eu-dcc-milan-1": "AWS14",
            "eu-dcc-dublin-1": "AWS14",
            "eu-dcc-dublin-2": "AWS14",
            "eu-dcc-milan-2": "AWS14",
            "eu-dcc-rating-1": "AWS14",
            "eu-dcc-rating-2": "AWS14",
            "ap-dcc-gazipur-1": "AWS15",
            "us-westjordan-1": "AWS16",
            "us-dcc-phoenix-1": "AWS17",
            "us-dcc-phoenix-2": "AWS17",
            "eu-jovanovac-1": "AWS20",
            "me-dcc-doha-1": "AWS21",
            "eu-dcc-rome-1": "AWS22",
            "us-somerset-1": "AWS23",
            "us-thames-1": "AWS23",
            "eu-dcc-zurich-1": "AWS24",
            "ap-dcc-tokyo-1": "AWS25",
            "me-abudhabi-3": "AWS26",
            "us-dcc-swjordan-1": "AWS27",
            "us-dcc-swjordan-2": "AWS28",
            "ap-hobsonville-1": "AWS31",
            "ap-tatebayashi-1": "AWS40",
            "uk-london-4": "AWS47",
        }
        if reg in region_map:
            return region_map[reg]

        if any(token in reg for token in ("gov", "dod", "ic.gov", "smil", "dcc")) or any(
            token in cluster for token in ("gov", "dod")
        ):
            return "GOV"
        if reg:
            return "AWS1"
        return "UNKNOWN"

    @staticmethod
    def _cluster_airport(cluster_name: str) -> str:
        """Extracts airport code from a cluster name and returns a short code (e.g., drz), while malformed names return empty text."""
        parts = (cluster_name or "").strip().lower().split("-")
        if len(parts) < 3:
            return ""
        return parts[-2]

    @staticmethod
    def _cluster_location_token(cluster_name: str) -> str:
        """Extracts location token after cluster index and returns text (e.g., ashburn), while malformed names return empty text."""
        text = (cluster_name or "").strip().lower()
        match = re.search(r"-cluster-\d+-(.+)-\d+$", text)
        if not match:
            return ""
        return str(match.group(1) or "").strip().lower()


    def _cluster_region_from_name(self, cluster_name: str, region_map: Dict[str, str]) -> str:
        """Derives AWS region from cluster name and returns region text (e.g., us-ashburn-1), while unknown patterns return empty text."""
        location = self._cluster_location_token(cluster_name)
        if not location:
            return ""

        # Full region token already embedded in cluster naming.
        if re.fullmatch(r"(af|ap|ca|eu|il|me|mx|sa|uk|us)-[a-z0-9-]+-\d+", location):
            return location

        # Airport-like token mapping from scripts.
        direct = str(region_map.get(location, "") or "").strip().lower()
        if direct:
            return direct

        # City/slug fallback (e.g., ashburn -> us-ashburn-1).
        alias_map: Dict[str, str] = {}

        def _is_gov_region(region_name: str) -> bool:
            region_text = str(region_name or "").strip().lower()
            return any(token in region_text for token in GOV_REGION_TOKENS)

        def _set_alias(alias: str, region_name: str) -> None:
            key = str(alias or "").strip().lower()
            value = str(region_name or "").strip().lower()
            if not key or not value:
                return
            current = alias_map.get(key)
            if not current:
                alias_map[key] = value
                return
            # Prefer non-government region when aliases collide (e.g., ashburn).
            if _is_gov_region(current) and not _is_gov_region(value):
                alias_map[key] = value

        for region in region_map.values():
            region_clean = str(region or "").strip().lower()
            if not re.fullmatch(r"(af|ap|ca|eu|il|me|mx|sa|uk|us)-[a-z0-9-]+-\d+", region_clean):
                continue
            parts = region_clean.split("-")
            if len(parts) < 3:
                continue
            middle = "-".join(parts[1:-1]).strip("-")
            if middle:
                _set_alias(middle, region_clean)
            if len(parts) >= 4:
                _set_alias("-".join(parts[2:-1]).strip("-"), region_clean)
            _set_alias(parts[-2], region_clean)
        return str(alias_map.get(location, "") or "").strip().lower()

    @staticmethod
    def _extract_cluster_names(text: str) -> Set[str]:
        """Finds cluster-like tokens in text and returns unique names (e.g., {pc-cluster-1-phx-1}), while malformed chunks are ignored."""
        found = set()
        for match in CLUSTER_TOKEN_RE.finditer(text or ""):
            token = match.group(0).strip().lower()
            if token:
                found.add(token)
        return found

    @staticmethod
    def _load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
        """Loads JSON from disk and returns an object map (e.g., {\"count\":1}), while parse or IO errors fall back to default."""
        try:
            if not path.exists():
                return dict(default)
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else dict(default)
        except Exception:
            return dict(default)

    @staticmethod
    def _save_json(path: Path, payload: Dict[str, Any]) -> None:
        """Writes JSON to disk and returns None, raising IO errors for invalid paths while dependency errors may bubble."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def _scan_files(root: Path) -> Iterable[Path]:
        """Enumerates scan-eligible files and returns an iterator of paths, while unreadable files are skipped."""
        if not root.exists():
            return []
        files: List[Path] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SCANNABLE_SUFFIXES:
                continue
            try:
                if path.stat().st_size > 2_000_000:
                    continue
            except Exception:
                continue
            files.append(path)
        return files

    def _airport_region_map(self) -> Dict[str, str]:
        """Builds airport-to-region map from bots scripts and returns a dictionary (e.g., {\"phx\":\"us-phoenix-1\"}), while missing scripts return a minimal map."""
        mapping: Dict[str, str] = {
            "phx": "us-phoenix-1",
            "iad": "us-ashburn-1",
            "ord": "us-chicago-1",
            "drz": "us-shawnee-1",
            "yyz": "ca-toronto-1",
            "lhr": "uk-london-1",
            "cwl": "uk-cardiff-1",
            "syd": "ap-sydney-1",
            "mel": "ap-melbourne-1",
            "bom": "ap-mumbai-1",
            "nrt": "ap-tokyo-1",
            "lin": "eu-milan-1",
            "cdg": "eu-paris-1",
            "fra": "eu-frankfurt-1",
            "dxb": "me-dubai-1",
            "auh": "me-abudhabi-1",
            "jnb": "af-johannesburg-1",
            "mrs": "eu-marseille-1",
            "mtz": "il-jerusalem-1",
            "mty": "mx-monterrey-1",
            "qro": "mx-queretaro-1",
            "vll": "sa-valparaiso-1",
            "vap": "sa-valparaiso-1",
            "aga": "us-saltlake-2",
        }
        update_script = self.cluster_scan_root / "scripts" / "update_kubeconfig.sh"
        if not update_script.exists():
            return mapping
        try:
            text = update_script.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return mapping
        for raw_line in text.splitlines():
            line = raw_line.strip()
            m = re.match(r'^([a-z0-9|*-]+)\)\s*echo\s+"([^"]+)"\s*;;?$', line)
            if not m:
                continue
            keys = [key.strip() for key in m.group(1).split("|")]
            region = m.group(2).strip().lower()
            if self._is_government_region_name(region):
                continue
            for key in keys:
                if not key or "*" in key or "-" in key:
                    continue
                if len(key) <= 6:
                    mapping[key.lower()] = region

        # Secondary mapping source from target lists such as:
        # p0.jnb.af-johannesburg-1 p0.mrs.eu-marseille-1 ...
        remove_ob4_script = self.cluster_scan_root / "scripts" / "remove-ob4-instances.sh"
        if remove_ob4_script.exists():
            try:
                text2 = remove_ob4_script.read_text(encoding="utf-8", errors="ignore")
                for airport, region in re.findall(r"\b[a-z0-9]+\.(?P<airport>[a-z0-9]+)\.(?P<region>[a-z0-9.-]+)\b", text2):
                    a = str(airport or "").strip().lower()
                    r = str(region or "").strip().lower()
                    if not a or not r:
                        continue
                    # Normalize known typo variants.
                    if r == "us-gov.ashburn-1":
                        r = "us-gov-ashburn-1"
                    if self._is_government_region_name(r):
                        continue
                    if len(a) <= 6 and "-" in r:
                        mapping[a] = r
            except Exception:
                pass
        return mapping

    def _environment_airport_region_map(self) -> Dict[Tuple[str, str], str]:
        """Builds environment+airport to region map from shepherd environments and returns a dictionary (e.g., {(\"p0\",\"jnb\"):\"af-johannesburg-1\"}), while unreadable files are skipped."""
        mapping: Dict[Tuple[str, str], str] = {}
        regions_dir = self.cluster_scan_root / "shepherd" / "shared_modules" / "environments" / "regions"
        if not regions_dir.exists():
            return mapping

        def _from_idcs_stripe(value: str) -> str:
            text = str(value or "").strip().lower()
            m = re.search(r"idcs-cloudservices-([a-z0-9-]+)-idcs-\d+$", text)
            if not m:
                return ""
            base = m.group(1).strip("-")
            # Most idcs stripes omit numeric suffix in region name; default to -1 when missing.
            if re.search(r"-\d+$", base):
                return base
            return f"{base}-1"

        for path in regions_dir.glob("*.json"):
            stem = path.stem.lower()
            # expected names like p0-jnb, pc-drz, p0-pub-phx, etc.
            m = re.match(r"^([a-z0-9]+)-(?:pub-)?([a-z0-9]+)$", stem)
            if not m:
                continue
            env = m.group(1)
            airport = m.group(2)
            if not env or not airport:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            idcs = payload.get("idcs") if isinstance(payload.get("idcs"), dict) else {}
            region = ""
            if idcs:
                region = _from_idcs_stripe(str(idcs.get("idcs_infra_stripe") or ""))
            if not region:
                # fallback: inspect URLs for region-like token
                blob = json.dumps(payload, ensure_ascii=False).lower()
                m_url = re.search(r"(?:https?://)?[a-z0-9.-]*\.(af|ap|ca|eu|il|me|mx|sa|uk|us)-[a-z0-9-]+-\d+", blob)
                if m_url:
                    # capture the full region token ending with -digit
                    m_full = re.search(r"((?:af|ap|ca|eu|il|me|mx|sa|uk|us)-[a-z0-9-]+-\d+)", blob)
                    if m_full:
                        region = m_full.group(1)
            if region:
                mapping[(env, airport)] = region
        return mapping

    @staticmethod
    def _profile_hint_for_realm(realm: str) -> str:
        """Builds default AWS profile hint for realm and returns a profile name (e.g., aws1), while unknown realms return empty text."""
        r = str(realm or "").strip().upper()
        if not r.startswith("OC"):
            return ""
        suffix = r[2:]
        if not suffix.isdigit():
            return ""
        return f"oc{suffix}"

    def _available_aws_profiles(self) -> Set[str]:
        """Reads local AWS config profile names and returns a set (e.g., {"aws1","aws1.ssh"}), while parse errors return empty."""
        if self._aws_profiles_cache is not None:
            return set(self._aws_profiles_cache)
        profiles: Set[str] = set()
        config_path = Path.home() / ".aws" / "config"
        try:
            if config_path.exists():
                for line in config_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    text = str(line or "").strip()
                    if not text.startswith("[") or not text.endswith("]"):
                        continue
                    name = text[1:-1].strip()
                    if name:
                        profiles.add(name)
        except Exception:
            profiles = set()
        self._aws_profiles_cache = set(profiles)
        return profiles

    def _preferred_profile_for_realm(self, realm: str) -> str:
        """Selects preferred AWS profile for realm and returns a profile (e.g., aws1.ssh), while unknown realms return empty."""
        base = self._profile_hint_for_realm(realm)
        if not base:
            return ""
        profiles = self._available_aws_profiles()
        ssh_profile = f"{base}.ssh"
        if ssh_profile in profiles:
            return ssh_profile
        if base in profiles:
            return base
        return ssh_profile

    def _configured_realm_profiles(self) -> Dict[str, str]:
        """Builds configured realm-profile map and returns entries (e.g., {"AWS1":"aws1.ssh"}), while bad env config falls back to defaults."""
        mapping: Dict[str, str] = dict(DEFAULT_REALM_PROFILE_MAP)
        raw = str(os.getenv("HERON_REALM_PROFILE_MAP") or "").strip()
        if raw:
            for token in raw.split(","):
                part = str(token or "").strip()
                if not part or "=" not in part:
                    continue
                realm, profile = part.split("=", maxsplit=1)
                realm_key = str(realm or "").strip().upper()
                profile_val = str(profile or "").strip()
                if realm_key and profile_val:
                    mapping[realm_key] = profile_val
        return mapping

    @staticmethod
    def _normalize_realm(value: str) -> str:
        """Normalizes realm string and returns canonical text (e.g., AWS1), while unknown values return UNKNOWN."""
        text = str(value or "").strip().upper()
        if not text:
            return "UNKNOWN"
        if text.startswith("OC") and text[2:].isdigit():
            return text
        return text

    def _load_mitigation_queue(self) -> None:
        """Loads persisted mitigation queue and returns None, while malformed payloads reset to an empty queue."""
        payload = self._load_json(self.audit_path, {})
        queue_payload = payload.get("mitigation_queue") if isinstance(payload.get("mitigation_queue"), dict) else {}
        entries = queue_payload.get("entries") if isinstance(queue_payload.get("entries"), list) else []
        normalized: List[Dict[str, Any]] = []
        for item in entries:
            if not isinstance(item, dict):
                continue
            ticket_key = str(item.get("ticket_key") or "").strip()
            if not ticket_key:
                continue
            normalized.append(
                {
                    "ticket_key": ticket_key,
                    "realm": self._normalize_realm(str(item.get("realm") or "UNKNOWN")),
                    "cluster": str(item.get("cluster") or "").strip(),
                    "summary": str(item.get("summary") or "").strip(),
                    "status": str(item.get("status") or "waiting_realm_auth").strip() or "waiting_realm_auth",
                    "queued_at_utc": str(item.get("queued_at_utc") or self._now_utc()),
                    "last_seen_utc": str(item.get("last_seen_utc") or self._now_utc()),
                    "release_note": str(item.get("release_note") or "").strip(),
                }
            )
        with self._realm_auth_lock:
            self._mitigation_queue = normalized

    def _persist_mitigation_queue(self) -> None:
        """Persists mitigation queue and returns None, while IO errors may bubble to callers."""
        with self._realm_auth_lock:
            queue_copy = [dict(item) for item in self._mitigation_queue]
        payload = self._load_json(self.audit_path, {})
        payload["mitigation_queue"] = {
            "generated_at_utc": self._now_utc(),
            "entries": queue_copy,
        }
        self._save_json(self.audit_path, payload)

    def _mark_queue_ready_realms(self, ready_realms: Set[str]) -> None:
        """Updates mitigation queue readiness and returns None, while unmatched entries remain waiting."""
        changed = False
        now = self._now_utc()
        with self._realm_auth_lock:
            for entry in self._mitigation_queue:
                realm = self._normalize_realm(str(entry.get("realm") or "UNKNOWN"))
                status = str(entry.get("status") or "waiting_realm_auth")
                if realm in ready_realms:
                    if status != "ready_to_run":
                        entry["status"] = "ready_to_run"
                        entry["release_note"] = "realm_auth_ready"
                        entry["last_seen_utc"] = now
                        changed = True
                else:
                    if status == "ready_to_run":
                        entry["status"] = "waiting_realm_auth"
                        entry["release_note"] = "realm_auth_not_ready"
                        entry["last_seen_utc"] = now
                        changed = True
        if changed:
            self._persist_mitigation_queue()

    def route_mitigation_by_realm(
        self,
        *,
        realm: str,
        ticket_key: str,
        cluster: str,
        summary: str,
    ) -> Dict[str, Any]:
        """Routes mitigation by realm readiness and returns a decision (e.g., {"decision":"proceed"}), while non-ready realms are queued."""
        normalized_realm = self._normalize_realm(realm)
        key = str(ticket_key or "").strip()
        state = self.get_realm_auth_status(refresh_if_stale=False)
        if not isinstance(state.get("profiles"), list) or not state.get("profiles"):
            state = self.get_realm_auth_status(refresh_if_stale=True)
        monitored_realms = {
            self._normalize_realm(str(item.get("realm") or ""))
            for item in (state.get("profiles") if isinstance(state.get("profiles"), list) else [])
            if isinstance(item, dict)
        }
        ready_realms = {
            self._normalize_realm(str(item))
            for item in (state.get("ready_realms") if isinstance(state.get("ready_realms"), list) else [])
        }
        if normalized_realm == "UNKNOWN" or normalized_realm not in monitored_realms:
            return {
                "decision": "proceed",
                "realm": normalized_realm,
                "reason": "realm_not_managed",
                "queued": False,
            }
        if normalized_realm in ready_realms:
            changed = False
            with self._realm_auth_lock:
                for entry in self._mitigation_queue:
                    if str(entry.get("ticket_key") or "").strip() != key:
                        continue
                    if entry.get("status") != "released":
                        entry["status"] = "released"
                        entry["release_note"] = "executed_after_realm_ready"
                        entry["last_seen_utc"] = self._now_utc()
                        changed = True
            if changed:
                self._persist_mitigation_queue()
            return {"decision": "proceed", "realm": normalized_realm, "reason": "realm_ready", "queued": False}

        queued_id = key or f"queue-{self._now_utc()}"
        now = self._now_utc()
        found = False
        with self._realm_auth_lock:
            for entry in self._mitigation_queue:
                if str(entry.get("ticket_key") or "").strip() != queued_id:
                    continue
                entry["realm"] = normalized_realm
                entry["cluster"] = str(cluster or "").strip()
                entry["summary"] = str(summary or "").strip()
                entry["status"] = "waiting_realm_auth"
                entry["last_seen_utc"] = now
                found = True
                break
            if not found:
                self._mitigation_queue.append(
                    {
                        "ticket_key": queued_id,
                        "realm": normalized_realm,
                        "cluster": str(cluster or "").strip(),
                        "summary": str(summary or "").strip(),
                        "status": "waiting_realm_auth",
                        "queued_at_utc": now,
                        "last_seen_utc": now,
                        "release_note": "",
                    }
                )
        self._persist_mitigation_queue()
        return {
            "decision": "queue",
            "realm": normalized_realm,
            "reason": "realm_auth_not_ready",
            "queued": True,
            "queue_id": queued_id,
        }

    def refresh_realm_auth_status(
        self,
        *,
        auto_refresh_session: bool = True,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """Refreshes realm auth health and returns state (e.g., {"ready_realms":["AWS1"]}), while CLI/tooling failures are captured."""
        mappings = self._configured_realm_profiles()
        rows: List[Dict[str, Any]] = []
        ready_realms: List[str] = []
        needs_login_realms: List[str] = []
        failed_realms: List[str] = []
        for realm, profile in sorted(mappings.items(), key=lambda item: item[0]):
            realm_key = self._normalize_realm(realm)
            profile_name = str(profile or "").strip()
            check = self._check_session_for_profile(profile_name, auto_refresh_session=auto_refresh_session)
            validate = check.get("validate") if isinstance(check.get("validate"), dict) else {}
            refresh = check.get("refresh") if isinstance(check.get("refresh"), dict) else {}
            valid = bool(check.get("valid"))
            refresh_attempted = bool(check.get("auto_refresh_attempted"))
            refresh_ok = bool(refresh.get("ok"))
            status = "ready" if valid else "needs_interactive_login"
            if valid and refresh_attempted and refresh_ok and not bool(validate.get("ok")):
                status = "ready_after_refresh"
            if valid:
                ready_realms.append(realm_key)
            elif refresh_attempted and not refresh_ok:
                needs_login_realms.append(realm_key)
            else:
                failed_realms.append(realm_key)
            rows.append(
                {
                    "realm": realm_key,
                    "profile": profile_name,
                    "ready": valid,
                    "status": status,
                    "needs_interactive_login": not valid,
                    "last_checked_utc": self._now_utc(),
                    "validate": validate,
                    "refresh": refresh,
                    "refresh_attempted": refresh_attempted,
                    "reauth_command": self._build_reauth_command(profile_name, ""),
                }
            )
        state = {
            "generated_at_utc": self._now_utc(),
            "profiles": rows,
            "ready_realms": sorted(set(ready_realms)),
            "needs_interactive_login_realms": sorted(set(needs_login_realms)),
            "summary": {
                "ready": len([row for row in rows if bool(row.get("ready"))]),
                "needs_interactive_login": len([row for row in rows if bool(row.get("needs_interactive_login"))]),
                "failed": len(failed_realms),
            },
        }
        with self._realm_auth_lock:
            self._realm_auth_state = state
        self._mark_queue_ready_realms(set(state["ready_realms"]))
        if persist:
            payload = self._load_json(self.audit_path, {})
            payload["realm_auth"] = state
            self._save_json(self.audit_path, payload)
        return state

    def get_realm_auth_status(self, *, refresh_if_stale: bool = True) -> Dict[str, Any]:
        """Gets latest realm auth state and returns board data (e.g., {"summary":{"ready":1}}), while stale data can be refreshed."""
        with self._realm_auth_lock:
            cached = dict(self._realm_auth_state)
        generated_at = str(cached.get("generated_at_utc") or "").strip()
        if not generated_at:
            audit = self._load_json(self.audit_path, {})
            realm_auth = audit.get("realm_auth") if isinstance(audit.get("realm_auth"), dict) else {}
            if realm_auth:
                with self._realm_auth_lock:
                    self._realm_auth_state = dict(realm_auth)
                cached = dict(realm_auth)
                generated_at = str(cached.get("generated_at_utc") or "").strip()
        if not refresh_if_stale:
            return cached
        try:
            if generated_at:
                last = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
                age_seconds = (datetime.now(timezone.utc) - last).total_seconds()
            else:
                age_seconds = 1_000_000
        except Exception:
            age_seconds = 1_000_000
        refresh_interval = max(
            15,
            int((os.getenv("HERON_REALM_AUTH_CHECK_INTERVAL_SECONDS") or "120").strip() or "120"),
        )
        if age_seconds >= refresh_interval:
            return self.refresh_realm_auth_status(auto_refresh_session=True, persist=True)
        return cached

    def start_realm_auth_monitor(self) -> None:
        """Starts background realm auth monitor and returns None, while duplicate starts are ignored."""
        enabled = str(os.getenv("HERON_REALM_AUTH_MONITOR_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}
        if not enabled:
            return
        with self._realm_auth_lock:
            if self._realm_auth_thread and self._realm_auth_thread.is_alive():
                return
            self._realm_auth_stop.clear()
            self._realm_auth_thread = Thread(target=self._realm_auth_loop, name="realm-auth-monitor", daemon=True)
            self._realm_auth_thread.start()

    def stop_realm_auth_monitor(self) -> None:
        """Stops background realm auth monitor and returns None, while absent threads are ignored."""
        self._realm_auth_stop.set()
        with self._realm_auth_lock:
            thread = self._realm_auth_thread
            self._realm_auth_thread = None
        if thread and thread.is_alive():
            thread.join(timeout=2)

    def _realm_auth_loop(self) -> None:
        """Runs background realm auth checks and returns None, while loop exceptions are swallowed to keep monitor alive."""
        while not self._realm_auth_stop.is_set():
            try:
                self.refresh_realm_auth_status(auto_refresh_session=True, persist=True)
            except Exception:
                pass
            interval = max(
                15,
                int((os.getenv("HERON_REALM_AUTH_CHECK_INTERVAL_SECONDS") or "120").strip() or "120"),
            )
            self._realm_auth_stop.wait(timeout=interval)

    def mitigation_queue_status(self) -> Dict[str, Any]:
        """Returns mitigation queue snapshot and returns a dictionary payload (e.g., {"count":1}), while empty queues return zero counts."""
        with self._realm_auth_lock:
            entries = [dict(item) for item in self._mitigation_queue]
        waiting = [item for item in entries if str(item.get("status") or "") == "waiting_realm_auth"]
        ready = [item for item in entries if str(item.get("status") or "") == "ready_to_run"]
        released = [item for item in entries if str(item.get("status") or "") == "released"]
        return {
            "generated_at_utc": self._now_utc(),
            "count": len(entries),
            "waiting_count": len(waiting),
            "ready_count": len(ready),
            "released_count": len(released),
            "entries": entries,
        }

    @staticmethod
    def _is_government(cluster_name: str, *, region: str = "") -> bool:
        """Flags government/DOD scope and returns True/False (e.g., False), while unknown values default to False."""
        text = (cluster_name or "").strip().lower()
        reg = (region or "").strip().lower()
        if any(token in text for token in GOV_CLUSTER_TOKENS):
            return True
        if any(token in reg for token in GOV_REGION_TOKENS):
            return True
        airport = ClusterAccessService._cluster_airport(text)
        return airport in GOV_AIRPORT_CODES

    @staticmethod
    def _build_reauth_command(profile: str, region: str) -> str:
        """Builds a local AWS re-auth command and returns a shell command string (e.g., aws session authenticate ...), while blank profile falls back to a generic command."""
        profile_clean = str(profile or "").strip()
        region_clean = str(region or "").strip()
        cmd = "aws session authenticate"
        if profile_clean:
            cmd += f" --profile-name {profile_clean}"
        if region_clean:
            cmd += f" --region {region_clean}"
        if DEFAULT_K8S_ACCOUNT_NAME:
            cmd += f" --account-name {DEFAULT_K8S_ACCOUNT_NAME}"
        if DEFAULT_K8S_AUTH_MODE:
            cmd += f" --auth {DEFAULT_K8S_AUTH_MODE}"
        return cmd

    def _build_kubeconfig_bootstrap_commands(
        self,
        *,
        cluster_name: str,
        environment: str,
        region: str,
        realm: str,
    ) -> Dict[str, str]:
        """Builds kubeconfig bootstrap commands and returns command hints (e.g., {"update_kubeconfig_command":"..."}), while missing metadata yields partial commands."""
        cluster = str(cluster_name or "").strip()
        env = str(environment or "").strip().lower() or self._cluster_environment(cluster)
        reg = str(region or "").strip().lower()
        if not reg:
            reg = self._cluster_region_from_name(cluster, self._airport_region_map())
        realm_text = str(realm or "").strip() or self._infer_realm(env, reg, cluster)
        profile = self._preferred_profile_for_realm(realm_text).lower()
        account = self._account_suffix_for_cluster(cluster)
        script = self.cluster_scan_root / "scripts" / "update_kubeconfig.sh"
        bulk_script = self.cluster_scan_root / "scripts" / "update-all-kubeconfigs.sh"
        host_root = str(os.getenv("HERON_CLUSTER_SCAN_HOST_ROOT") or str(Path.home() / ".kube")).strip()
        host_script = f"{host_root}/scripts/update_kubeconfig.sh"
        host_bulk_script = f"{host_root}/scripts/update-all-kubeconfigs.sh"
        update_cmd = ""
        if script.exists() and profile and reg and env and cluster and account:
            update_cmd = (
                f"{host_script} {shlex.quote(profile)} {shlex.quote(reg)} "
                f"{shlex.quote(env)} {shlex.quote(cluster)} {shlex.quote(account)}"
            )
        bulk_env_cmd = ""
        bulk_all_cmd = ""
        if bulk_script.exists() and profile:
            if env:
                bulk_env_cmd = f"{host_bulk_script} {shlex.quote(env)} {shlex.quote(profile)}"
            bulk_all_cmd = f"{host_bulk_script} all {shlex.quote(profile)}"
        expected_path = (f"~/.kube/config.{cluster}" if cluster else "")
        verify_cmd = (f"test -s ~/.kube/config.{cluster} && echo OK || echo MISSING" if cluster else "")
        single_cluster_cmd = ""
        if update_cmd and verify_cmd:
            single_cluster_cmd = f"{update_cmd} && {verify_cmd}"
        elif update_cmd:
            single_cluster_cmd = update_cmd
        return {
            "update_kubeconfig_command": update_cmd,
            "update_all_kubeconfigs_env_command": bulk_env_cmd,
            "update_all_kubeconfigs_all_command": bulk_all_cmd,
            "expected_kubeconfig_path": expected_path,
            "verify_kubeconfig_command": verify_cmd,
            "single_cluster_bootstrap_command": single_cluster_cmd,
            "profile": profile,
            "region": reg,
            "environment": env,
            "account": account,
        }

    @staticmethod
    def _clusters_from_local_kubeconfigs() -> Set[str]:
        """Discovers cluster names from local kubeconfig files and returns a set (e.g., {"pc-cluster-1-phx-1"}), while unreadable files are ignored."""
        clusters: Set[str] = set()
        kube_dir = Path.home() / ".kube"
        try:
            for path in kube_dir.glob("config.*"):
                name = path.name
                if not path.is_file():
                    continue
                try:
                    if path.stat().st_size <= 0:
                        continue
                except Exception:
                    continue
                cluster = str(name[len("config."):]).strip().lower()
                if not cluster:
                    continue
                if not CLUSTER_TOKEN_RE.fullmatch(cluster):
                    continue
                clusters.add(cluster)
        except Exception:
            return set()
        return clusters

    def _build_candidate_rows(
        self,
        clusters: Set[str],
        region_map: Dict[str, str],
        env_airport_region_map: Dict[Tuple[str, str], str],
        *,
        include_government: bool,
        kubeconfig_clusters: Set[str] | None = None,
    ) -> List[Dict[str, Any]]:
        """Converts raw cluster names into structured rows and returns a list (e.g., [{\"cluster\":\"pc-cluster-1-phx-1\"}]), while invalid names are skipped."""
        rows: List[Dict[str, Any]] = []
        canonical_clusters = sorted({self._canonical_cluster_name(value) for value in clusters if self._canonical_cluster_name(value)})
        for cluster in canonical_clusters:
            if self._is_excluded_cluster(cluster):
                continue
            airport = self._cluster_airport(cluster)
            environment = self._cluster_environment(cluster)
            env_region = str(env_airport_region_map.get((environment, airport), "") or "").strip().lower()
            name_region = self._cluster_region_from_name(cluster, region_map)
            airport_region = str(region_map.get(airport, "") or "").strip().lower()
            region = env_region or name_region or airport_region
            account = self._infer_account(environment)
            realm = self._infer_realm(environment, region, cluster)
            profile_hint = self._preferred_profile_for_realm(realm)
            gov = self._is_government(cluster, region=region) or self._is_government_realm(realm)
            if gov and not include_government:
                continue
            mapping_source = "airport_map"
            if env_region:
                mapping_source = "env_airport_map"
            elif name_region:
                mapping_source = "cluster_name_map"
            if isinstance(kubeconfig_clusters, set) and cluster in kubeconfig_clusters:
                mapping_source = "kubeconfig_file"
            rows.append(
                {
                    "cluster": cluster,
                    "name": cluster,
                    "environment": environment,
                    "airport_code": airport,
                    "region": region,
                    "realm": realm,
                    "account": account,
                    "mapping_source": mapping_source,
                    "profile_hint": profile_hint,
                    "refresh_command_hint": (f"aws --profile {profile_hint} session refresh" if profile_hint else ""),
                    "validate_command_hint": (f"aws --profile {profile_hint} session validate --local" if profile_hint else ""),
                    "government": gov,
                }
            )
        return rows

    def discover(self, *, include_government: bool = False, max_clusters: int = 0, persist: bool = True) -> Dict[str, Any]:
        """Scans HERON_CLUSTER_SCAN_ROOT for cluster names and returns inventory rows (e.g., {\"count\":2,\"targets\":[...]}), while unreadable files are ignored."""
        roots = [self.cluster_scan_root]
        scan_errors: List[str] = []
        kubeconfig_clusters = self._clusters_from_local_kubeconfigs()
        found_clusters: Set[str] = set(kubeconfig_clusters)
        scanned_files = 0

        for root in roots:
            try:
                for path in self._scan_files(root):
                    scanned_files += 1
                    try:
                        text = path.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        continue
                    found_clusters.update(self._extract_cluster_names(text))
            except Exception as exc:
                scan_errors.append(f"{root}: {exc}")

        region_map = self._airport_region_map()
        env_airport_region_map = self._environment_airport_region_map()
        rows = self._build_candidate_rows(
            found_clusters,
            region_map,
            env_airport_region_map,
            include_government=include_government,
            kubeconfig_clusters=kubeconfig_clusters,
        )
        if max_clusters and max_clusters > 0:
            rows = rows[:max_clusters]

        payload = {
            "generated_at_utc": self._now_utc(),
            "cluster_scan_root": str(self.cluster_scan_root),
            "include_government": bool(include_government),
            "scanned_files": scanned_files,
            "local_kubeconfigs_total": len(kubeconfig_clusters),
            "clusters_total": len(rows),
            "targets": rows,
            "errors": scan_errors,
            "auth_readiness": {
                "kubectl_in_path": bool(shutil.which("kubectl")),
                "aws_in_path": bool(shutil.which("aws")),
                "home_kube_exists": Path.home().joinpath(".kube").exists(),
                "home_aws_exists": Path.home().joinpath(".aws").exists(),
            },
            "recommended_methods": [
                {
                    "method": "existing_cluster_kubeconfigs",
                    "path": str(Path.home() / ".kube"),
                    "stability": "high",
                    "notes": "Primary path: use ~/.kube/config.<cluster> files and run read-only kubectl probes per cluster.",
                },
                {
                    "method": "aws_create_kubeconfig",
                    "stability": "medium",
                    "notes": "Fallback path: generate kubeconfig via `aws ce cluster create-kubeconfig` when local files are missing.",
                },
                {
                    "method": "update_kubeconfig",
                    "path": str(self.cluster_scan_root / "scripts" / "update_kubeconfig.sh"),
                    "stability": "high",
                    "notes": "Use this to generate missing ~/.kube/config.<cluster> entries with region/profile mapping.",
                },
                {
                    "method": "update_all_kubeconfigs",
                    "path": str(self.cluster_scan_root / "scripts" / "update-all-kubeconfigs.sh"),
                    "stability": "high",
                    "notes": "Use this to bulk-generate kubeconfigs by environment or for all supported environments.",
                },
            ],
        }
        if persist:
            existing = self._load_json(self.audit_path, {})
            existing["discovery"] = payload
            self._save_json(self.audit_path, existing)
        return payload

    @staticmethod
    def _run_kubectl_check(kubeconfig: str, args: List[str], timeout: int) -> Dict[str, Any]:
        """Executes a read-only kubectl command and returns a command result (e.g., {\"success\":true}), while timeout/exec errors are captured."""
        if not shutil.which("kubectl"):
            return {"success": False, "code": -1, "stdout": "", "stderr": "kubectl not found", "command": ""}
        cmd = ["kubectl", "--kubeconfig", kubeconfig] + args
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return {
                "success": proc.returncode == 0,
                "code": proc.returncode,
                "stdout": (proc.stdout or "")[:1200],
                "stderr": (proc.stderr or "")[:800],
                "command": " ".join(cmd),
            }
        except Exception as exc:
            return {"success": False, "code": -1, "stdout": "", "stderr": str(exc), "command": " ".join(cmd)}

    @staticmethod
    def _parse_kubeconfig_exec_metadata(kubeconfig: str) -> Dict[str, str]:
        """Parses kubeconfig exec auth fields and returns metadata (e.g., {\"profile\":\"aws.ssh\"}), while malformed files return empty values."""
        result = {"profile": "", "region": "", "auth": "", "command": ""}
        try:
            payload = yaml.safe_load(Path(kubeconfig).read_text(encoding="utf-8")) or {}
            if not isinstance(payload, dict):
                return result
            users = payload.get("users")
            if not isinstance(users, list) or not users:
                return result
            user_obj = users[0].get("user") if isinstance(users[0], dict) else {}
            if not isinstance(user_obj, dict):
                return result
            exec_obj = user_obj.get("exec")
            if not isinstance(exec_obj, dict):
                return result
            command = str(exec_obj.get("command") or "").strip()
            args = exec_obj.get("args") if isinstance(exec_obj.get("args"), list) else []
            result["command"] = command
            for idx, token in enumerate(args):
                if not isinstance(token, str):
                    continue
                if token == "--profile" and idx + 1 < len(args) and isinstance(args[idx + 1], str):
                    result["profile"] = args[idx + 1].strip()
                elif token == "--region" and idx + 1 < len(args) and isinstance(args[idx + 1], str):
                    result["region"] = args[idx + 1].strip()
                elif token == "--auth" and idx + 1 < len(args) and isinstance(args[idx + 1], str):
                    result["auth"] = args[idx + 1].strip()
            return result
        except Exception:
            return result

    @staticmethod
    def _run_aws_session_validate(profile: str, *, timeout: int = 15) -> Dict[str, Any]:
        """Runs AWS local session validation and returns status (e.g., {\"valid\":true}), while CLI errors are captured."""
        if not profile:
            return {"ok": False, "valid": False, "code": -1, "stderr": "missing_profile"}
        if not shutil.which("aws"):
            return {"ok": False, "valid": False, "code": -1, "stderr": "aws_not_found"}
        cmd = ["aws", "--profile", profile, "session", "validate", "--local"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            stdout = (proc.stdout or "").strip()
            stderr = (proc.stderr or "").strip()
            valid = proc.returncode == 0
            return {
                "ok": valid,
                "valid": valid,
                "code": proc.returncode,
                "stdout": stdout[:500],
                "stderr": stderr[:500],
                "command": " ".join(cmd),
            }
        except Exception as exc:
            return {"ok": False, "valid": False, "code": -1, "stdout": "", "stderr": str(exc), "command": " ".join(cmd)}

    @staticmethod
    def _run_aws_session_refresh(profile: str, *, timeout: int = 25) -> Dict[str, Any]:
        """Runs AWS session refresh and returns status (e.g., {\"ok\":true}), while network or auth errors are captured."""
        if not profile:
            return {"ok": False, "code": -1, "stderr": "missing_profile"}
        if not shutil.which("aws"):
            return {"ok": False, "code": -1, "stderr": "aws_not_found"}
        cmd = ["aws", "--profile", profile, "session", "refresh"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return {
                "ok": proc.returncode == 0,
                "code": proc.returncode,
                "stdout": (proc.stdout or "")[:800],
                "stderr": (proc.stderr or "")[:800],
                "command": " ".join(cmd),
            }
        except Exception as exc:
            return {"ok": False, "code": -1, "stdout": "", "stderr": str(exc), "command": " ".join(cmd)}

    def _check_session_for_profile(self, profile: str, *, auto_refresh_session: bool) -> Dict[str, Any]:
        """Checks AWS session for one profile and returns validate/refresh details (e.g., {\"valid\":true}), while command errors are captured."""
        result: Dict[str, Any] = {
            "profile": str(profile or "").strip(),
            "validate": {"ok": False, "valid": False, "code": -1, "stderr": "not_checked"},
            "refresh": {"ok": False, "code": -1, "stderr": "refresh_not_attempted"},
            "auto_refresh_attempted": bool(auto_refresh_session),
            "valid": False,
        }
        if not result["profile"]:
            result["validate"] = {"ok": False, "valid": False, "code": -1, "stderr": "missing_profile"}
            result["auto_refresh_attempted"] = False
            return result
        validate_state = self._run_aws_session_validate(result["profile"])
        refresh_state: Dict[str, Any] = {"ok": False, "code": -1, "stderr": "refresh_not_attempted"}
        if not validate_state.get("valid") and auto_refresh_session:
            refresh_state = self._run_aws_session_refresh(result["profile"])
            if refresh_state.get("ok"):
                validate_state = self._run_aws_session_validate(result["profile"])
        result["validate"] = validate_state
        result["refresh"] = refresh_state
        result["valid"] = bool(validate_state.get("valid"))
        return result

    @staticmethod
    def _run_aws_command(args: List[str], *, timeout: int = 30) -> Dict[str, Any]:
        """Executes an AWS CLI command and returns result details (e.g., {"ok":true,"stdout":"..."}), while execution errors are captured."""
        if not shutil.which("aws"):
            return {"ok": False, "code": -1, "stdout": "", "stderr": "aws_not_found", "command": " ".join(args)}
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
            return {
                "ok": proc.returncode == 0,
                "code": proc.returncode,
                "stdout": (proc.stdout or "").strip(),
                "stderr": (proc.stderr or "").strip(),
                "command": " ".join(args),
            }
        except Exception as exc:
            return {"ok": False, "code": -1, "stdout": "", "stderr": str(exc), "command": " ".join(args)}

    def _resolve_account_id(
        self,
        *,
        profile: str,
        account_id: str,
        account_name: str,
    ) -> Tuple[str, str]:
        """Resolves a account AWSID and returns (account_id,error) (e.g., ("awsid1.account...","")), while lookup failures return an error reason."""
        home_region_cmd = [
            "aws",
            "--auth",
            "security_token",
            "iam",
            "region-subscription",
            "list",
            "--account-id",
            account_id,
            "--all",
            "--profile",
            profile,
            "--query",
            'data[?"is-home-region"==`true`]."region-name" | [0]',
            "--raw-output",
        ]
        home_region_result = self._run_aws_command(home_region_cmd, timeout=25)
        if not home_region_result.get("ok"):
            return "", str(home_region_result.get("stderr") or "home_region_lookup_failed")
        home_region = str(home_region_result.get("stdout") or "").strip()
        if not home_region or home_region.lower() == "null":
            return "", "home_region_missing"

        account_cmd = [
            "aws",
            "--auth",
            "security_token",
            "iam",
            "account",
            "list",
            "--region",
            home_region,
            "--profile",
            profile,
            "--account-id",
            account_id,
            "--all",
            "--query",
            f"data[?name=='{account_name}'].id | [0]",
            "--raw-output",
        ]
        account_result = self._run_aws_command(account_cmd, timeout=25)
        if not account_result.get("ok"):
            return "", str(account_result.get("stderr") or "account_lookup_failed")
        account_id = str(account_result.get("stdout") or "").strip()
        if not account_id or account_id.lower() == "null":
            return "", f"account_not_found:{account_name}"
        return account_id, ""

    def _check_cluster_active_in_aws(
        self,
        *,
        cluster_name: str,
        environment: str,
        region: str,
        realm: str,
        account_suffix: str,
    ) -> Dict[str, Any]:
        """Checks AWS cluster lifecycle and returns active-state metadata (e.g., {"checked":true,"active":false}), while auth/dependency errors are returned as not-checked reasons."""
        env = str(environment or "").strip().lower()
        reg = str(region or "").strip().lower()
        if not reg:
            reg = self._cluster_region_from_name(cluster_name, self._airport_region_map())
        profile = self._preferred_profile_for_realm(realm)
        if not profile:
            return {"checked": False, "active": None, "reason": "missing_profile", "profile": "", "lifecycle_state": ""}
        if not reg:
            return {"checked": False, "active": None, "reason": "missing_region", "profile": profile, "lifecycle_state": ""}

        account_ids = self._script_environment_account_ids()
        account_id = str(account_ids.get(env) or "").strip()
        if not account_id:
            return {"checked": False, "active": None, "reason": f"unsupported_environment:{env}", "profile": profile, "lifecycle_state": ""}

        session_state = self._run_aws_session_validate(profile)
        if profile in self._session_validate_cache:
            session_valid = bool(self._session_validate_cache.get(profile))
        else:
            session_valid = bool(session_state.get("valid"))
            self._session_validate_cache[profile] = session_valid
        if not session_valid:
            return {"checked": False, "active": None, "reason": "session_invalid", "profile": profile, "lifecycle_state": ""}

        account_name = f"{env}-{str(account_suffix or 'dp').strip().lower() or 'dp'}"
        cache_key = (profile, account_id, account_name)
        if cache_key in self._account_cache:
            account_id, account_error = self._account_cache[cache_key]
        else:
            account_id, account_error = self._resolve_account_id(
                profile=profile,
                account_id=account_id,
                account_name=account_name,
            )
            self._account_cache[cache_key] = (account_id, account_error)
        if not account_id:
            return {
                "checked": False,
                "active": None,
                "reason": account_error or "account_lookup_failed",
                "profile": profile,
                "lifecycle_state": "",
            }

        active_lookup_cmd = [
            "aws",
            "--auth",
            "security_token",
            "ce",
            "cluster",
            "list",
            "--lifecycle-state",
            "ACTIVE",
            "--all",
            "--region",
            reg,
            "--profile",
            profile,
            "--account-id",
            account_id,
            "--name",
            cluster_name,
            "--query",
            "data | length(@)",
            "--raw-output",
        ]
        active_lookup = self._run_aws_command(active_lookup_cmd, timeout=30)
        if not active_lookup.get("ok"):
            return {
                "checked": False,
                "active": None,
                "reason": str(active_lookup.get("stderr") or "active_lookup_failed"),
                "profile": profile,
                "lifecycle_state": "",
            }
        active_count = str(active_lookup.get("stdout") or "").strip()
        if active_count.isdigit() and int(active_count) > 0:
            return {"checked": True, "active": True, "reason": "", "profile": profile, "lifecycle_state": "ACTIVE"}

        any_state_cmd = [
            "aws",
            "--auth",
            "security_token",
            "ce",
            "cluster",
            "list",
            "--all",
            "--region",
            reg,
            "--profile",
            profile,
            "--account-id",
            account_id,
            "--name",
            cluster_name,
            "--query",
            'data[0]."lifecycle-state"',
            "--raw-output",
        ]
        any_state_lookup = self._run_aws_command(any_state_cmd, timeout=30)
        if not any_state_lookup.get("ok"):
            return {
                "checked": False,
                "active": None,
                "reason": str(any_state_lookup.get("stderr") or "state_lookup_failed"),
                "profile": profile,
                "lifecycle_state": "",
            }
        lifecycle_state = str(any_state_lookup.get("stdout") or "").strip().upper()
        if not lifecycle_state or lifecycle_state.lower() == "null":
            return {"checked": True, "active": False, "reason": "not_found_in_aws", "profile": profile, "lifecycle_state": ""}
        return {"checked": True, "active": False, "reason": f"state:{lifecycle_state.lower()}", "profile": profile, "lifecycle_state": lifecycle_state}

    def validate(
        self,
        *,
        clusters: List[Dict[str, Any]] | None = None,
        include_government: bool = False,
        max_clusters: int = 250,
        command_timeout_seconds: int = 25,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """Validates read-only Kubernetes access per cluster and returns results (e.g., {\"accessible\":10,\"failed\":2}), while command errors are recorded."""
        source = clusters
        if source is None:
            source = self._load_json(self.audit_path, {}).get("discovery", {}).get("targets")
        items = source if isinstance(source, list) else []

        checked = 0
        accessible = 0
        failed = 0
        non_active = 0
        skipped = 0
        results: List[Dict[str, Any]] = []
        auto_refresh_session = str(os.getenv("HERON_CLUSTER_ACCESS_AUTO_REFRESH_SESSION", "true")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        for item in items:
            if checked >= max(1, max_clusters):
                break
            if isinstance(item, str):
                row = {"cluster": item}
            elif isinstance(item, dict):
                row = dict(item)
            else:
                continue
            cluster_name = self._canonical_cluster_name(str(row.get("cluster") or row.get("cluster_name") or ""))
            if not cluster_name:
                continue
            if self._is_excluded_cluster(cluster_name):
                continue
            region = str(row.get("region") or "").strip().lower()
            if self._is_government(cluster_name, region=region) and not include_government:
                skipped += 1
                results.append(
                    {
                        "cluster": cluster_name,
                        "region": region,
                        "realm": str(row.get("realm") or self._infer_realm(str(row.get("environment") or ""), region, cluster_name)),
                        "account": str(row.get("account") or self._infer_account(str(row.get("environment") or ""))),
                        "status": "skipped_government",
                        "accessible": False,
                        "reason": "excluded_by_policy",
                    }
                )
                continue
            checked += 1
            environment = str(row.get("environment") or self._cluster_environment(cluster_name))
            realm = str(row.get("realm") or self._infer_realm(environment, region, cluster_name))
            active_check = self._check_cluster_active_in_aws(
                cluster_name=cluster_name,
                environment=environment,
                region=region,
                realm=realm,
                account_suffix=self._account_suffix_for_cluster(cluster_name),
            )
            if bool(active_check.get("checked")) and active_check.get("active") is False:
                non_active += 1
                results.append(
                    {
                        "cluster": cluster_name,
                        "region": region,
                        "realm": realm,
                        "account": str(row.get("account") or self._infer_account(environment)),
                        "environment": environment,
                        "status": "non_active_cluster",
                        "accessible": False,
                        "reason": str(active_check.get("reason") or "cluster_not_active"),
                        "lifecycle_state": str(active_check.get("lifecycle_state") or ""),
                        "active_check": active_check,
                    }
                )
                continue
            from app.integrations.kubernetes import get_kubeconfig_for_cluster
            kubeconfig = get_kubeconfig_for_cluster(
                cluster_name,
                account_id=str(row.get("account_id") or "").strip() or None,
            )
            if not kubeconfig:
                failed += 1
                bootstrap = self._build_kubeconfig_bootstrap_commands(
                    cluster_name=cluster_name,
                    environment=environment,
                    region=region,
                    realm=realm,
                )
                results.append(
                    {
                        "cluster": cluster_name,
                        "region": region,
                        "realm": realm,
                        "account": str(row.get("account") or self._infer_account(environment)),
                        "environment": environment,
                        "status": "kubeconfig_missing",
                        "accessible": False,
                        "reason": "could_not_resolve_kubeconfig",
                        "remediation": {
                            "help": "Generate kubeconfig for this cluster locally, then run Validate Access again.",
                            "update_kubeconfig_command": bootstrap.get("update_kubeconfig_command", ""),
                            "update_all_kubeconfigs_env_command": bootstrap.get("update_all_kubeconfigs_env_command", ""),
                            "update_all_kubeconfigs_all_command": bootstrap.get("update_all_kubeconfigs_all_command", ""),
                            "expected_kubeconfig_path": bootstrap.get("expected_kubeconfig_path", ""),
                            "verify_kubeconfig_command": bootstrap.get("verify_kubeconfig_command", ""),
                            "single_cluster_bootstrap_command": bootstrap.get("single_cluster_bootstrap_command", ""),
                            "profile": bootstrap.get("profile", ""),
                            "region": bootstrap.get("region", ""),
                            "environment": bootstrap.get("environment", ""),
                            "account": bootstrap.get("account", ""),
                        },
                    }
                )
                continue
            exec_meta = self._parse_kubeconfig_exec_metadata(kubeconfig)
            exec_profile = str(exec_meta.get("profile", "") or "").strip()
            auth_mode = (exec_meta.get("auth", "") or "").lower()
            if exec_profile and auth_mode == "security_token":
                region_from_exec = str(exec_meta.get("region") or region)
                realm_for_profile = str(
                    row.get("realm")
                    or self._infer_realm(str(row.get("environment") or ""), region_from_exec, cluster_name)
                )
                realm_profile = self._profile_hint_for_realm(realm_for_profile)
                candidate_profiles: List[str] = []
                for candidate in (exec_profile, realm_profile):
                    c = str(candidate or "").strip()
                    if c and c not in candidate_profiles:
                        candidate_profiles.append(c)
                session_checks = [self._check_session_for_profile(profile_name, auto_refresh_session=auto_refresh_session) for profile_name in candidate_profiles]
                exec_session = session_checks[0] if session_checks else {"valid": False}
                if not bool(exec_session.get("valid")):
                    failed += 1
                    remediation_profile = exec_profile
                    reauth_cmd = self._build_reauth_command(remediation_profile, region_from_exec)
                    alternative_profile = realm_profile if realm_profile and realm_profile != remediation_profile else ""
                    alternative_reauth_command = (
                        self._build_reauth_command(alternative_profile, region_from_exec) if alternative_profile else ""
                    )
                    missing_aws_tooling = any(
                        str((check.get("validate") or {}).get("stderr") or "").strip() == "aws_not_found"
                        for check in session_checks
                    )
                    reason = "aws_cli_missing" if missing_aws_tooling else "aws_session_expired"
                    status = "dependency_missing_aws_cli" if missing_aws_tooling else "auth_session_expired"
                    if alternative_profile and any(
                        bool(check.get("valid"))
                        for check in session_checks
                        if str(check.get("profile") or "").strip() == alternative_profile
                    ):
                        reason = "aws_session_expired_profile_mismatch"
                    results.append(
                        {
                            "cluster": cluster_name,
                            "environment": str(row.get("environment") or self._cluster_environment(cluster_name)),
                            "airport_code": str(row.get("airport_code") or self._cluster_airport(cluster_name)),
                            "region": region_from_exec,
                            "realm": str(
                                row.get("realm")
                                or self._infer_realm(str(row.get("environment") or ""), region_from_exec, cluster_name)
                            ),
                            "account": str(row.get("account") or self._infer_account(str(row.get("environment") or ""))),
                            "kubeconfig": kubeconfig,
                            "kubeconfig_source": (
                                "home_kube"
                                if kubeconfig.startswith(str(Path.home() / ".kube"))
                                else ("generated_tmp" if kubeconfig.startswith("/tmp/") else "custom")
                            ),
                            "status": status,
                            "accessible": False,
                            "reason": reason,
                            "session": {
                                "checks": session_checks,
                                "auto_refresh_attempted": bool(auto_refresh_session),
                            },
                            "remediation": {
                                "profile": remediation_profile,
                                "suggested_profile": (alternative_profile or remediation_profile),
                                "region": region_from_exec,
                                "account_name": DEFAULT_K8S_ACCOUNT_NAME,
                                "auth_mode": DEFAULT_K8S_AUTH_MODE,
                                "reauth_command": reauth_cmd,
                                "refresh_command": f"aws --profile {remediation_profile} session refresh",
                                "validate_command": f"aws --profile {remediation_profile} session validate --local",
                                "alternative_reauth_command": alternative_reauth_command,
                                "note": "Re-auth with the kubeconfig profile, then run full Validate Access for API reachability.",
                            },
                            "checks": {},
                        }
                    )
                    continue
            current_ctx = self._run_kubectl_check(kubeconfig, ["config", "current-context"], timeout=command_timeout_seconds)
            raw_version = self._run_kubectl_check(kubeconfig, ["get", "--raw=/version"], timeout=command_timeout_seconds)
            ns_check = self._run_kubectl_check(
                kubeconfig,
                ["get", "ns", "--request-timeout=20s"],
                timeout=command_timeout_seconds,
            )
            ok = bool(current_ctx.get("success")) and bool(raw_version.get("success")) and bool(ns_check.get("success"))
            failure_reason = ""
            if not ok:
                errs = " ".join(
                    [
                        str(current_ctx.get("stderr") or ""),
                        str(raw_version.get("stderr") or ""),
                        str(ns_check.get("stderr") or ""),
                    ]
                ).strip()
                lower_errs = errs.lower()
                if "this cli session has expired" in lower_errs:
                    failure_reason = "aws_session_expired"
                elif auth_mode == "security_token" and str(raw_version.get("stderr") or "").strip() == "Abort:":
                    failure_reason = "aws_session_expired_probable"
                elif "connect: operation not permitted" in lower_errs or "operation not permitted" in lower_errs:
                    failure_reason = "kube_api_network_blocked"
                elif "i/o timeout" in lower_errs or "timed out" in lower_errs:
                    failure_reason = "kube_api_timeout"
                elif "no such host" in lower_errs:
                    failure_reason = "kube_api_dns_error"
                elif "connection refused" in lower_errs:
                    failure_reason = "kube_api_connection_refused"
            if ok:
                accessible += 1
            else:
                failed += 1
            results.append(
                {
                    "cluster": cluster_name,
                    "environment": str(row.get("environment") or self._cluster_environment(cluster_name)),
                    "airport_code": str(row.get("airport_code") or self._cluster_airport(cluster_name)),
                    "region": region,
                    "realm": str(row.get("realm") or self._infer_realm(str(row.get("environment") or ""), region, cluster_name)),
                    "account": str(row.get("account") or self._infer_account(str(row.get("environment") or ""))),
                    "kubeconfig": kubeconfig,
                    "kubeconfig_source": (
                        "home_kube"
                        if kubeconfig.startswith(str(Path.home() / ".kube"))
                        else ("generated_tmp" if kubeconfig.startswith("/tmp/") else "custom")
                    ),
                    "status": "ok" if ok else "failed",
                    "accessible": ok,
                    "reason": failure_reason,
                    "checks": {
                        "current_context": current_ctx,
                        "api_version": raw_version,
                        "namespaces": ns_check,
                    },
                }
            )

        payload = {
            "generated_at_utc": self._now_utc(),
            "checked": checked,
            "accessible": accessible,
            "failed": failed,
            "non_active": non_active,
            "skipped_government": skipped,
            "results": results,
        }
        if persist:
            existing = self._load_json(self.audit_path, {})
            existing["validation"] = payload
            existing["non_active_clusters"] = {
                "generated_at_utc": payload["generated_at_utc"],
                "entries": [
                    {
                        "cluster": str(row.get("cluster") or ""),
                        "region": str(row.get("region") or ""),
                        "realm": str(row.get("realm") or ""),
                        "account": str(row.get("account") or ""),
                        "environment": str(row.get("environment") or ""),
                        "lifecycle_state": str(row.get("lifecycle_state") or ""),
                        "reason": str(row.get("reason") or ""),
                    }
                    for row in results
                    if isinstance(row, dict) and str(row.get("status") or "").strip() == "non_active_cluster"
                ],
            }
            self._save_json(self.audit_path, existing)
        return payload

    def validate_auth_only(
        self,
        *,
        clusters: List[Dict[str, Any]] | None = None,
        include_government: bool = False,
        max_clusters: int = 250,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """Validates only AWS auth sessions and returns auth-focused results (e.g., {"auth_ok":10,"auth_failed":2}), while command errors are captured."""
        source = clusters
        if source is None:
            audit = self._load_json(self.audit_path, {})
            validation_rows = ((audit.get("validation") or {}).get("results") or []) if isinstance(audit, dict) else []
            expired_rows = [
                row for row in validation_rows if isinstance(row, dict) and str(row.get("status") or "").strip() == "auth_session_expired"
            ] if isinstance(validation_rows, list) else []
            if expired_rows:
                source = expired_rows
            else:
                discovered_rows = ((audit.get("discovery") or {}).get("targets") or []) if isinstance(audit, dict) else []
                source = discovered_rows if isinstance(discovered_rows, list) else []
        items = source if isinstance(source, list) else []

        checked = 0
        auth_ok = 0
        auth_failed = 0
        auth_not_required = 0
        skipped = 0
        non_active = 0
        results: List[Dict[str, Any]] = []
        auto_refresh_session = str(os.getenv("HERON_CLUSTER_ACCESS_AUTO_REFRESH_SESSION", "true")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        for item in items:
            if checked >= max(1, max_clusters):
                break
            if isinstance(item, str):
                row = {"cluster": item}
            elif isinstance(item, dict):
                row = dict(item)
            else:
                continue
            cluster_name = self._canonical_cluster_name(str(row.get("cluster") or row.get("cluster_name") or ""))
            if not cluster_name:
                continue
            if self._is_excluded_cluster(cluster_name):
                continue
            region = str(row.get("region") or "").strip().lower()
            if self._is_government(cluster_name, region=region) and not include_government:
                skipped += 1
                results.append(
                    {
                        "cluster": cluster_name,
                        "region": region,
                        "realm": str(row.get("realm") or self._infer_realm(str(row.get("environment") or ""), region, cluster_name)),
                        "account": str(row.get("account") or self._infer_account(str(row.get("environment") or ""))),
                        "status": "skipped_government",
                        "accessible": False,
                        "reason": "excluded_by_policy",
                    }
                )
                continue

            checked += 1
            environment = str(row.get("environment") or self._cluster_environment(cluster_name))
            realm = str(row.get("realm") or self._infer_realm(environment, region, cluster_name))
            active_check = self._check_cluster_active_in_aws(
                cluster_name=cluster_name,
                environment=environment,
                region=region,
                realm=realm,
                account_suffix=self._account_suffix_for_cluster(cluster_name),
            )
            if bool(active_check.get("checked")) and active_check.get("active") is False:
                non_active += 1
                results.append(
                    {
                        "cluster": cluster_name,
                        "region": region,
                        "realm": realm,
                        "account": str(row.get("account") or self._infer_account(environment)),
                        "environment": environment,
                        "status": "non_active_cluster",
                        "accessible": False,
                        "reason": str(active_check.get("reason") or "cluster_not_active"),
                        "lifecycle_state": str(active_check.get("lifecycle_state") or ""),
                        "active_check": active_check,
                    }
                )
                continue
            from app.integrations.kubernetes import get_kubeconfig_for_cluster

            kubeconfig = get_kubeconfig_for_cluster(
                cluster_name,
                account_id=str(row.get("account_id") or "").strip() or None,
            )
            if not kubeconfig:
                auth_failed += 1
                bootstrap = self._build_kubeconfig_bootstrap_commands(
                    cluster_name=cluster_name,
                    environment=environment,
                    region=region,
                    realm=realm,
                )
                results.append(
                    {
                        "cluster": cluster_name,
                        "region": region,
                        "realm": realm,
                        "account": str(row.get("account") or self._infer_account(environment)),
                        "environment": environment,
                        "status": "kubeconfig_missing",
                        "accessible": False,
                        "reason": "could_not_resolve_kubeconfig",
                        "remediation": {
                            "help": "Generate kubeconfig for this cluster locally before auth re-validation.",
                            "update_kubeconfig_command": bootstrap.get("update_kubeconfig_command", ""),
                            "update_all_kubeconfigs_env_command": bootstrap.get("update_all_kubeconfigs_env_command", ""),
                            "update_all_kubeconfigs_all_command": bootstrap.get("update_all_kubeconfigs_all_command", ""),
                            "expected_kubeconfig_path": bootstrap.get("expected_kubeconfig_path", ""),
                            "verify_kubeconfig_command": bootstrap.get("verify_kubeconfig_command", ""),
                            "single_cluster_bootstrap_command": bootstrap.get("single_cluster_bootstrap_command", ""),
                            "profile": bootstrap.get("profile", ""),
                            "region": bootstrap.get("region", ""),
                            "environment": bootstrap.get("environment", ""),
                            "account": bootstrap.get("account", ""),
                        },
                    }
                )
                continue

            exec_meta = self._parse_kubeconfig_exec_metadata(kubeconfig)
            exec_profile = str(exec_meta.get("profile", "") or "").strip()
            auth_mode = (exec_meta.get("auth", "") or "").lower()
            region_from_exec = str(exec_meta.get("region") or region)
            realm_for_profile = str(
                row.get("realm")
                or self._infer_realm(str(row.get("environment") or ""), region_from_exec, cluster_name)
            )
            realm_profile = self._profile_hint_for_realm(realm_for_profile)
            candidate_profiles: List[str] = []
            for candidate in (exec_profile, realm_profile):
                c = str(candidate or "").strip()
                if c and c not in candidate_profiles:
                    candidate_profiles.append(c)

            if auth_mode != "security_token" or not candidate_profiles:
                auth_not_required += 1
                results.append(
                    {
                        "cluster": cluster_name,
                        "environment": str(row.get("environment") or self._cluster_environment(cluster_name)),
                        "airport_code": str(row.get("airport_code") or self._cluster_airport(cluster_name)),
                        "region": region_from_exec,
                        "realm": realm_for_profile,
                        "account": str(row.get("account") or self._infer_account(str(row.get("environment") or ""))),
                        "kubeconfig": kubeconfig,
                        "kubeconfig_source": (
                            "home_kube"
                            if kubeconfig.startswith(str(Path.home() / ".kube"))
                            else ("generated_tmp" if kubeconfig.startswith("/tmp/") else "custom")
                        ),
                        "status": "auth_not_required",
                        "accessible": True,
                        "reason": "",
                        "session": {"checks": [], "auto_refresh_attempted": bool(auto_refresh_session)},
                        "checks": {},
                    }
                )
                continue

            session_checks = [
                self._check_session_for_profile(profile_name, auto_refresh_session=auto_refresh_session)
                for profile_name in candidate_profiles
            ]
            valid_session = any(bool(check.get("valid")) for check in session_checks)
            remediation_profile = exec_profile or candidate_profiles[0]
            alternative_profile = realm_profile if realm_profile and realm_profile != remediation_profile else ""
            reauth_cmd = self._build_reauth_command(remediation_profile, region_from_exec)
            alternative_reauth_command = (
                self._build_reauth_command(alternative_profile, region_from_exec) if alternative_profile else ""
            )
            if valid_session:
                auth_ok += 1
            else:
                auth_failed += 1
            results.append(
                {
                    "cluster": cluster_name,
                    "environment": str(row.get("environment") or self._cluster_environment(cluster_name)),
                    "airport_code": str(row.get("airport_code") or self._cluster_airport(cluster_name)),
                    "region": region_from_exec,
                    "realm": realm_for_profile,
                    "account": str(row.get("account") or self._infer_account(str(row.get("environment") or ""))),
                    "kubeconfig": kubeconfig,
                    "kubeconfig_source": (
                        "home_kube"
                        if kubeconfig.startswith(str(Path.home() / ".kube"))
                        else ("generated_tmp" if kubeconfig.startswith("/tmp/") else "custom")
                    ),
                    "status": "auth_ok" if valid_session else "auth_session_expired",
                    "accessible": bool(valid_session),
                    "reason": "" if valid_session else "aws_session_expired",
                    "session": {"checks": session_checks, "auto_refresh_attempted": bool(auto_refresh_session)},
                    "remediation": {
                        "profile": remediation_profile,
                        "suggested_profile": (alternative_profile or remediation_profile),
                        "region": region_from_exec,
                        "account_name": DEFAULT_K8S_ACCOUNT_NAME,
                        "auth_mode": DEFAULT_K8S_AUTH_MODE,
                        "reauth_command": reauth_cmd,
                        "refresh_command": f"aws --profile {remediation_profile} session refresh",
                        "validate_command": f"aws --profile {remediation_profile} session validate --local",
                        "alternative_reauth_command": alternative_reauth_command,
                        "note": "Run local re-auth for the kubeconfig profile, then run full validation for cluster API reachability.",
                    },
                    "checks": {},
                }
            )

        payload = {
            "generated_at_utc": self._now_utc(),
            "checked": checked,
            "auth_ok": auth_ok,
            "auth_failed": auth_failed,
            "auth_not_required": auth_not_required,
            "non_active": non_active,
            "skipped_government": skipped,
            "results": results,
        }
        if persist:
            existing = self._load_json(self.audit_path, {})
            existing["validation_auth"] = payload
            if "non_active_clusters" not in existing:
                existing["non_active_clusters"] = {
                    "generated_at_utc": payload["generated_at_utc"],
                    "entries": [
                        {
                            "cluster": str(row.get("cluster") or ""),
                            "region": str(row.get("region") or ""),
                            "realm": str(row.get("realm") or ""),
                            "account": str(row.get("account") or ""),
                            "environment": str(row.get("environment") or ""),
                            "lifecycle_state": str(row.get("lifecycle_state") or ""),
                            "reason": str(row.get("reason") or ""),
                        }
                        for row in results
                        if isinstance(row, dict) and str(row.get("status") or "").strip() == "non_active_cluster"
                    ],
                }
            self._save_json(self.audit_path, existing)
        return payload

    def apply_validated_targets(self, *, accessible_only: bool = True, include_government: bool = False) -> Dict[str, Any]:
        """Builds cluster target config from validated clusters and returns save details (e.g., {\"saved\":true,\"count\":10}), while file IO errors may bubble."""
        audit = self._load_json(self.audit_path, {})
        discovered = audit.get("discovery", {}).get("targets")
        validation = audit.get("validation", {}).get("results")
        discovered_rows = discovered if isinstance(discovered, list) else []
        validation_rows = validation if isinstance(validation, list) else []

        discovered_by_cluster: Dict[str, Dict[str, Any]] = {}
        for row in discovered_rows:
            if not isinstance(row, dict):
                continue
            cluster = str(row.get("cluster") or "").strip().lower()
            if cluster:
                discovered_by_cluster[cluster] = row

        validation_by_cluster: Dict[str, Dict[str, Any]] = {}
        for row in validation_rows:
            if not isinstance(row, dict):
                continue
            cluster = str(row.get("cluster") or "").strip().lower()
            if cluster:
                validation_by_cluster[cluster] = row

        final_targets: List[Dict[str, Any]] = []
        for cluster, row in sorted(discovered_by_cluster.items()):
            if self._is_excluded_cluster(cluster):
                continue
            merged = dict(row)
            merged.update(validation_by_cluster.get(cluster, {}))
            region = str(merged.get("region") or "").strip().lower()
            if self._is_government(cluster, region=region) and not include_government:
                continue
            if accessible_only and not bool(merged.get("accessible")):
                continue
            final_targets.append(
                {
                    "name": str(merged.get("name") or cluster),
                    "cluster": cluster,
                    "region": str(merged.get("region") or ""),
                    "environment": str(merged.get("environment") or self._cluster_environment(cluster)),
                    "account_id": str(merged.get("account_id") or ""),
                    "service": "cluster-hygiene",
                    "tier": "platform",
                    "enabled": True,
                    "collect_details": True,
                    "collect_top_metrics": True,
                    "collect_events": True,
                    "events_tail_count": 100,
                    "cleanup_evicted_enabled": False,
                    "cleanup_completed_enabled": False,
                    "cleanup_failed_enabled": False,
                    "labels": {
                        "source": "cluster_access_validation",
                        "airport_code": str(merged.get("airport_code") or ""),
                    },
                }
            )

        payload = {"targets": final_targets}
        self._save_json(self.cluster_targets_path, payload)
        return {
            "saved": True,
            "path": str(self.cluster_targets_path),
            "count": len(final_targets),
            "accessible_only": bool(accessible_only),
            "include_government": bool(include_government),
        }

    def status(self) -> Dict[str, Any]:
        """Returns latest discovery/validation snapshots and environment readiness (e.g., {\"has_discovery\":true}), while missing data yields empty defaults."""
        payload = self._load_json(self.audit_path, {})
        validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {"results": []}
        validation_auth = payload.get("validation_auth") if isinstance(payload.get("validation_auth"), dict) else {"results": []}
        discovery = payload.get("discovery") if isinstance(payload.get("discovery"), dict) else {"targets": []}
        discovery_targets = discovery.get("targets") if isinstance(discovery.get("targets"), list) else []
        raw_validation_rows = validation.get("results") if isinstance(validation.get("results"), list) else []
        raw_validation_auth_rows = validation_auth.get("results") if isinstance(validation_auth.get("results"), list) else []
        local_kubeconfig_clusters = self._clusters_from_local_kubeconfigs()

        def _normalize_auth_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            normalized: List[Dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                current = dict(row)
                cluster_key = self._canonical_cluster_name(str(current.get("cluster") or ""))
                status = str(current.get("status") or "").strip()
                if status == "auth_session_expired" and cluster_key and cluster_key in local_kubeconfig_clusters:
                    current["status"] = "kubeconfig_present"
                    current["reason"] = "local_kubeconfig_present"
                    current["accessible"] = False
                normalized.append(current)
            return normalized

        validation_rows = _normalize_auth_rows(raw_validation_rows)
        validation_auth_rows = _normalize_auth_rows(raw_validation_auth_rows)
        non_active_rows: List[Dict[str, Any]] = []
        for source in (validation_rows, validation_auth_rows):
            for row in source:
                if not isinstance(row, dict):
                    continue
                if str(row.get("status") or "").strip() != "non_active_cluster":
                    continue
                reason = str(row.get("reason") or "")
                if reason.startswith("stale_cluster_index_exceeds_capacity:"):
                    continue
                non_active_rows.append(
                    {
                        "cluster": str(row.get("cluster") or ""),
                        "region": str(row.get("region") or ""),
                        "realm": str(row.get("realm") or ""),
                        "account": str(row.get("account") or ""),
                        "environment": str(row.get("environment") or ""),
                        "lifecycle_state": str(row.get("lifecycle_state") or ""),
                        "reason": str(row.get("reason") or ""),
                    }
                )
        non_active_by_cluster: Dict[str, Dict[str, Any]] = {}
        for row in non_active_rows:
            key = self._canonical_cluster_name(str(row.get("cluster") or ""))
            if key and key not in non_active_by_cluster:
                non_active_by_cluster[key] = row
        non_active_set = set(non_active_by_cluster.keys())

        filtered_discovery_targets = [
            row
            for row in discovery_targets
            if (
                isinstance(row, dict)
                and self._canonical_cluster_name(str(row.get("cluster") or "")) not in non_active_set
                and not self._is_excluded_cluster(self._canonical_cluster_name(str(row.get("cluster") or "")))
            )
        ]
        filtered_validation_rows = [
            row
            for row in validation_rows
            if (
                isinstance(row, dict)
                and self._canonical_cluster_name(str(row.get("cluster") or "")) not in non_active_set
                and not self._is_excluded_cluster(self._canonical_cluster_name(str(row.get("cluster") or "")))
            )
        ]
        filtered_validation_auth_rows = [
            row
            for row in validation_auth_rows
            if (
                isinstance(row, dict)
                and self._canonical_cluster_name(str(row.get("cluster") or "")) not in non_active_set
                and not self._is_excluded_cluster(self._canonical_cluster_name(str(row.get("cluster") or "")))
            )
        ]

        filtered_discovery = dict(discovery)
        filtered_discovery["targets"] = filtered_discovery_targets
        filtered_discovery["clusters_total"] = len(filtered_discovery_targets)
        filtered_validation = dict(validation)
        filtered_validation["results"] = filtered_validation_rows
        filtered_validation_auth = dict(validation_auth)
        filtered_validation_auth["results"] = filtered_validation_auth_rows

        rows = filtered_validation_auth_rows if filtered_validation_auth_rows else filtered_validation_rows
        env_map, region_map = self._script_realm_mappings()
        realm_catalog = sorted({*env_map.values(), *region_map.values()})
        failed_auth_rows: List[Dict[str, Any]] = []
        unique_commands: Set[str] = set()
        missing_kubeconfig_rows: List[Dict[str, Any]] = []
        missing_kubeconfig_commands: Set[str] = set()
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                remediation = row.get("remediation") if isinstance(row.get("remediation"), dict) else {}
                status = str(row.get("status") or "").strip()
                if status == "auth_session_expired":
                    command = str(remediation.get("reauth_command") or "").strip()
                    alt_command = str(remediation.get("alternative_reauth_command") or "").strip()
                    if command:
                        unique_commands.add(command)
                    if alt_command:
                        unique_commands.add(alt_command)
                    failed_auth_rows.append(
                        {
                            "cluster": str(row.get("cluster") or ""),
                            "profile": str(remediation.get("profile") or ""),
                            "suggested_profile": str(remediation.get("suggested_profile") or remediation.get("profile") or ""),
                            "region": str(remediation.get("region") or row.get("region") or ""),
                            "command": command,
                            "alternative_command": alt_command,
                        }
                    )
                if status == "kubeconfig_missing":
                    cluster_name = self._canonical_cluster_name(str(row.get("cluster") or remediation.get("cluster") or ""))
                    environment = str(remediation.get("environment") or row.get("environment") or self._cluster_environment(cluster_name))
                    region = str(remediation.get("region") or row.get("region") or "").strip().lower()
                    realm = str(row.get("realm") or remediation.get("realm") or self._infer_realm(environment, region, cluster_name))
                    bootstrap = self._build_kubeconfig_bootstrap_commands(
                        cluster_name=cluster_name,
                        environment=environment,
                        region=region,
                        realm=realm,
                    )
                    single_cluster_cmd = str(bootstrap.get("single_cluster_bootstrap_command") or "").strip()
                    update_cmd = str(bootstrap.get("update_kubeconfig_command") or "").strip()
                    bulk_env_cmd = str(bootstrap.get("update_all_kubeconfigs_env_command") or "").strip()
                    bulk_all_cmd = str(bootstrap.get("update_all_kubeconfigs_all_command") or "").strip()
                    verify_cmd = str(bootstrap.get("verify_kubeconfig_command") or "").strip()
                    expected_path = str(bootstrap.get("expected_kubeconfig_path") or "")
                    profile = str(bootstrap.get("profile") or remediation.get("profile") or "")
                    account = str(bootstrap.get("account") or remediation.get("account") or "")
                    if single_cluster_cmd:
                        missing_kubeconfig_commands.add(single_cluster_cmd)
                    elif update_cmd:
                        missing_kubeconfig_commands.add(update_cmd)
                    elif verify_cmd:
                        missing_kubeconfig_commands.add(verify_cmd)
                    missing_kubeconfig_rows.append(
                        {
                            "cluster": cluster_name,
                            "environment": environment,
                            "region": region,
                            "profile": profile,
                            "account": account,
                            "single_cluster_bootstrap_command": single_cluster_cmd,
                            "update_kubeconfig_command": update_cmd,
                            "update_all_kubeconfigs_env_command": bulk_env_cmd,
                            "update_all_kubeconfigs_all_command": bulk_all_cmd,
                            "expected_kubeconfig_path": expected_path,
                            "verify_kubeconfig_command": verify_cmd,
                        }
                    )
        realm_auth = self.get_realm_auth_status(refresh_if_stale=True)
        mitigation_queue = self.mitigation_queue_status()
        return {
            "audit_path": str(self.audit_path),
            "has_discovery": isinstance(payload.get("discovery"), dict),
            "has_validation": isinstance(payload.get("validation"), dict),
            "has_validation_auth": isinstance(payload.get("validation_auth"), dict),
            "discovery": filtered_discovery,
            "validation": filtered_validation,
            "validation_auth": filtered_validation_auth,
            "realm_catalog": realm_catalog,
            "non_active_clusters": {
                "count": len(non_active_by_cluster),
                "entries": list(non_active_by_cluster.values()),
                "hidden_from_ui": True,
            },
            "reauth": {
                "required": bool(failed_auth_rows),
                "account_name": DEFAULT_K8S_ACCOUNT_NAME,
                "auth_mode": DEFAULT_K8S_AUTH_MODE,
                "entries": failed_auth_rows,
                "commands": sorted(unique_commands),
                "help": "Run reauth command in your local host terminal, complete browser login, then click Re-Validate.",
            },
            "kubeconfig_bootstrap": {
                "required": bool(missing_kubeconfig_rows),
                "entries": missing_kubeconfig_rows,
                "commands": sorted(missing_kubeconfig_commands),
                "help": "Run commands one cluster at a time (serial), then run Validate Access; bulk script options are available per entry when needed.",
            },
            "realm_auth": realm_auth,
            "mitigation_queue": mitigation_queue,
            "auth_readiness": {
                "kubectl_in_path": bool(shutil.which("kubectl")),
                "aws_in_path": bool(shutil.which("aws")),
                "home_kube_exists": Path.home().joinpath(".kube").exists(),
                "home_aws_exists": Path.home().joinpath(".aws").exists(),
            },
        }


cluster_access_service = ClusterAccessService()
