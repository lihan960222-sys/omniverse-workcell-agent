import argparse
import importlib.metadata
import json
import platform
import sys


PACKAGE_REQUIREMENTS = {
    "mcp": ">=1.28,<2", "pydantic": ">=2.11,<3", "aiohttp": ">=3.12,<4",
    "httpx": ">=0.28,<1", "jinja2": ">=3.1,<4", "packaging": ">=24,<27",
    "usd-core": "==25.11", "cadquery-ocp": "==7.9.3.1.1",
}
ISAAC_PACKAGES = {"pydantic", "aiohttp", "jinja2", "packaging"}
ISAAC_EXTENSIONS = {
    "omni.usd": None,
    "omni.ui": None,
    "omni.timeline": None,
    "omni.physx": "110.3.2",
    "omni.asset_validator.core": "1.20.1",
    "isaacsim.asset.validation": "2.2.0",
    "isaacsim.core.experimental.prims": "1.10.8",
    "isaacsim.core.simulation_manager": "1.17.1",
    "isaacsim.core.version": "2.2.1",
}


def _runtime_details(app):
    manager = app.get_extension_manager()
    extensions = {}
    for name, expected in ISAAC_EXTENSIONS.items():
        extension_id = manager.get_enabled_extension_id(name)
        version = manager.get_extension_dict(extension_id)["package"]["version"] if extension_id else None
        extensions[name] = {"enabled": bool(extension_id), "id": extension_id,
                            "version": version, "expected_version": expected}
    details = {"isaac_version": None, "isaac_version_components": None,
               "app_name": app.get_app_name(), "app_version": app.get_app_version(),
               "kit_version": app.get_kit_version(), "kit_kernel_version": app.get_kernel_version(),
               "usd_version": None, "physics_engine": None, "extensions": extensions,
               "validator_version": None, "validation_categories": [], "enabled_validation_categories": []}
    if extensions["isaacsim.core.version"]["enabled"]:
        from isaacsim.core.version import get_version

        version = get_version()
        details.update(isaac_version=version[0], isaac_version_components=list(version))
    if extensions["isaacsim.core.simulation_manager"]["enabled"]:
        from isaacsim.core.simulation_manager import SimulationManager

        details["physics_engine"] = SimulationManager.get_active_physics_engine()
    if extensions["omni.usd"]["enabled"]:
        from pxr import Usd

        details["usd_version"] = list(Usd.GetVersion())
    if extensions["omni.asset_validator.core"]["enabled"]:
        import omni.asset_validator.core as validator

        details.update(validator_version=validator.get_version(),
                       validation_categories=sorted(validator.ValidationRulesRegistry.categories()),
                       enabled_validation_categories=sorted(validator.ValidationRulesRegistry.categories(enabledOnly=True)))
    return details


def check_environment(target: str | None = None) -> dict:
    if target not in {None, "core", "isaac"}:
        raise ValueError(f"未知环境检查目标: {target}")
    installed = {distribution.metadata["Name"].lower().replace("_", "-"): distribution.version
                 for distribution in importlib.metadata.distributions() if distribution.metadata["Name"]}
    running = False
    app = None
    if "omni.kit.app" in sys.modules:
        import omni.kit.app

        app = omni.kit.app.get_app()
        running = app.is_running()
    target = target or ("isaac" if running else "core")
    required = ISAAC_PACKAGES if target == "isaac" else PACKAGE_REQUIREMENTS
    missing = [name for name in required if name not in installed]
    mismatches = []
    if "packaging" in installed:
        from packaging.specifiers import SpecifierSet

        for name in required:
            if name in installed and installed[name] not in SpecifierSet(PACKAGE_REQUIREMENTS[name]):
                mismatches.append({"component": name, "actual": installed[name],
                                   "expected": PACKAGE_REQUIREMENTS[name]})
    if not (3, 11) <= sys.version_info[:2] < (3, 14):
        mismatches.append({"component": "python", "actual": platform.python_version(), "expected": ">=3.11,<3.14"})
    runtime = _runtime_details(app) if running else None
    if target == "isaac":
        if not running:
            missing.append("isaac_runtime")
        else:
            expected_values = {"isaac_version": "6.1.0", "physics_engine": "physx"}
            for component, expected in expected_values.items():
                if runtime[component] != expected:
                    mismatches.append({"component": component, "actual": runtime[component], "expected": expected})
            if "packaging" in installed:
                from packaging.version import Version

                if Version(runtime["kit_version"]).base_version != "110.3.0":
                    mismatches.append({"component": "kit_version", "actual": runtime["kit_version"],
                                       "expected": "110.3.0"})
            for name, details in runtime["extensions"].items():
                if not details["enabled"]:
                    missing.append(name)
                elif details["expected_version"] and details["version"] != details["expected_version"]:
                    mismatches.append({"component": name, "actual": details["version"],
                                       "expected": details["expected_version"]})
            if not runtime["validation_categories"]:
                missing.append("validation_categories")
        for component, actual, expected in (("platform", platform.system(), "Linux"),
                                             ("machine", platform.machine(), "x86_64"),
                                             ("python", f"{sys.version_info.major}.{sys.version_info.minor}", "3.12")):
            if actual != expected:
                mismatches.append({"component": component, "actual": actual, "expected": expected})
    return {"target": target, "status": "unavailable" if missing or mismatches else "ready",
            "python": platform.python_version(), "platform": platform.system(), "machine": platform.machine(),
            "packages": {name: installed.get(name) for name in (*PACKAGE_REQUIREMENTS, "isaacsim")},
            "isaac_running": running, "runtime": runtime,
            "required_missing": sorted(missing), "version_mismatches": mismatches}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["core", "isaac"], default="core")
    args = parser.parse_args()
    report = check_environment(args.target)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "ready":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
