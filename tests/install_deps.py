"""Helper to install missing dependencies into venv site-packages."""
import subprocess
import sys
import os

def test_install_celery_redis():
    """Install celery and redis if not already available."""
    try:
        import celery
        import redis
        print(f"celery {celery.__version__} and redis already installed")
        return
    except ImportError:
        pass

    site_packages = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "venv", "lib", "python3.14", "site-packages"
    )
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install",
         "--target", site_packages,
         "celery==5.4.0", "redis==5.2.0"],
        capture_output=True, text=True
    )
    print(result.stdout[-3000:])
    if result.returncode != 0:
        print("STDERR:", result.stderr[-1000:])
    assert result.returncode == 0, f"pip install failed:\n{result.stderr}"

    # Verify
    import importlib
    importlib.invalidate_caches()
    import celery  # noqa
    import redis   # noqa
    print(f"Successfully installed celery {celery.__version__}")
