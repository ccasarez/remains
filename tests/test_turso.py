"""Tests for Turso/libSQL persistence layer — connection routing and DSN handling."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from dregs.store import DregsStore


# ---------------------------------------------------------------------------
# Constructor: DSN resolution
# ---------------------------------------------------------------------------


class TestConstructorDSN:
    """DregsStore constructor should accept path, URL, or fall back to env."""

    def test_explicit_file_path_string(self, tmp_path):
        db = tmp_path / "test.db"
        store = DregsStore(str(db))
        assert store._dsn == str(db)

    def test_explicit_file_path_pathlib(self, tmp_path):
        db = tmp_path / "test.db"
        store = DregsStore(db)
        assert store._dsn == str(db)

    def test_explicit_url(self):
        store = DregsStore("libsql://mydb-myorg.turso.io")
        assert store._dsn == "libsql://mydb-myorg.turso.io"

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setenv("DREGS_DSN", "libsql://env-db.turso.io")
        store = DregsStore()
        assert store._dsn == "libsql://env-db.turso.io"

    def test_env_var_fallback_file_path(self, tmp_path, monkeypatch):
        db = tmp_path / "env.db"
        monkeypatch.setenv("DREGS_DSN", str(db))
        store = DregsStore()
        assert store._dsn == str(db)

    def test_explicit_overrides_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DREGS_DSN", "libsql://env-db.turso.io")
        db = tmp_path / "explicit.db"
        store = DregsStore(str(db))
        assert store._dsn == str(db)

    def test_no_dsn_raises(self, monkeypatch):
        monkeypatch.delenv("DREGS_DSN", raising=False)
        with pytest.raises(ValueError, match="No DSN"):
            DregsStore()

    def test_none_dsn_no_env_raises(self, monkeypatch):
        monkeypatch.delenv("DREGS_DSN", raising=False)
        with pytest.raises(ValueError, match="No DSN"):
            DregsStore(None)

    def test_conn_initially_none(self, tmp_path):
        store = DregsStore(tmp_path / "test.db")
        assert store._conn is None


# ---------------------------------------------------------------------------
# Connection routing: _connect() picks the right driver
# ---------------------------------------------------------------------------


class TestConnectionRouting:
    """_connect() should select sqlite3 for file paths and libsql for URLs."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        """Ensure ambient Turso env vars don't leak into connection-routing tests."""
        monkeypatch.delenv("DREGS_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("DREGS_SYNC_URL", raising=False)

    def test_local_file_uses_sqlite3(self, tmp_path):
        db = tmp_path / "local.db"
        store = DregsStore(str(db))
        conn = store._connect()
        assert isinstance(conn, sqlite3.Connection)
        store.close()

    def test_libsql_url_uses_libsql(self):
        """A libsql:// URL should use libsql.connect()."""
        import libsql

        fake_conn = MagicMock()
        with patch.object(libsql, "connect", return_value=fake_conn) as mock_connect:
            store = DregsStore("libsql://mydb-myorg.turso.io")
            conn = store._connect()
            mock_connect.assert_called_once_with(
                database="libsql://mydb-myorg.turso.io",
                auth_token="",
            )
            assert conn is fake_conn

    def test_https_url_uses_libsql(self):
        """An https:// URL should use libsql.connect()."""
        import libsql

        fake_conn = MagicMock()
        with patch.object(libsql, "connect", return_value=fake_conn) as mock_connect:
            store = DregsStore("https://mydb-myorg.turso.io")
            conn = store._connect()
            mock_connect.assert_called_once_with(
                database="https://mydb-myorg.turso.io",
                auth_token="",
            )
            assert conn is fake_conn

    def test_http_url_uses_libsql(self):
        """An http:// URL should use libsql.connect()."""
        import libsql

        fake_conn = MagicMock()
        with patch.object(libsql, "connect", return_value=fake_conn) as mock_connect:
            store = DregsStore("http://localhost:8080")
            conn = store._connect()
            mock_connect.assert_called_once_with(
                database="http://localhost:8080",
                auth_token="",
            )
            assert conn is fake_conn

    def test_auth_token_from_env(self, monkeypatch):
        """Auth token should be read from DREGS_AUTH_TOKEN env var."""
        import libsql

        monkeypatch.setenv("DREGS_AUTH_TOKEN", "secret-token")
        fake_conn = MagicMock()
        with patch.object(libsql, "connect", return_value=fake_conn) as mock_connect:
            store = DregsStore("libsql://mydb-myorg.turso.io")
            store._connect()
            mock_connect.assert_called_once_with(
                database="libsql://mydb-myorg.turso.io",
                auth_token="secret-token",
            )

    def test_embedded_replica_mode(self, tmp_path, monkeypatch):
        """When DREGS_SYNC_URL is set with a file path DSN, use embedded replica."""
        import libsql

        monkeypatch.setenv("DREGS_SYNC_URL", "libsql://mydb-myorg.turso.io")
        monkeypatch.setenv("DREGS_AUTH_TOKEN", "token123")

        fake_conn = MagicMock()
        with patch.object(libsql, "connect", return_value=fake_conn) as mock_connect:
            db = str(tmp_path / "replica.db")
            store = DregsStore(db)
            conn = store._connect()
            mock_connect.assert_called_once_with(
                database=db,
                sync_url="libsql://mydb-myorg.turso.io",
                auth_token="token123",
            )
            fake_conn.sync.assert_called_once()

    def test_connection_cached(self, tmp_path):
        """Second call to _connect() should return the same connection."""
        store = DregsStore(str(tmp_path / "test.db"))
        conn1 = store._connect()
        conn2 = store._connect()
        assert conn1 is conn2
        store.close()

    def test_close_resets_conn(self, tmp_path):
        """close() should set _conn back to None."""
        store = DregsStore(str(tmp_path / "test.db"))
        store._connect()
        store.close()
        assert store._conn is None

    def test_pragma_wal_set_on_local(self, tmp_path):
        """Local SQLite connections should have WAL journal mode."""
        store = DregsStore(str(tmp_path / "test.db"))
        conn = store._connect()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        store.close()

    def test_pragma_errors_swallowed_on_remote(self):
        """PRAGMA failures on remote connections should not raise."""
        import libsql

        fake_conn = MagicMock()
        fake_conn.execute.side_effect = [Exception("not supported"), Exception("not supported")]
        with patch.object(libsql, "connect", return_value=fake_conn):
            store = DregsStore("libsql://mydb-myorg.turso.io")
            # Should not raise even though PRAGMAs fail
            conn = store._connect()
            assert conn is fake_conn


# ---------------------------------------------------------------------------
# ImportError when libsql not installed
# ---------------------------------------------------------------------------


class TestLibsqlImportError:
    """When libsql is not installed, a helpful ImportError should be raised."""

    def test_remote_url_without_libsql(self):
        with patch.dict("sys.modules", {"libsql": None}):
            store = DregsStore("libsql://mydb-myorg.turso.io")
            with pytest.raises(ImportError, match="libsql"):
                store._connect()

    def test_sync_url_without_libsql(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DREGS_SYNC_URL", "libsql://mydb-myorg.turso.io")
        with patch.dict("sys.modules", {"libsql": None}):
            store = DregsStore(str(tmp_path / "replica.db"))
            with pytest.raises(ImportError, match="libsql"):
                store._connect()


# ---------------------------------------------------------------------------
# Backward compatibility: db_path attribute
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    """DregsStore("path") should still expose db_path for backward compat."""

    def test_db_path_set_for_local_file(self, tmp_path):
        db = tmp_path / "test.db"
        store = DregsStore(db)
        assert store.db_path == db

    def test_db_path_none_for_url(self):
        store = DregsStore("libsql://mydb-myorg.turso.io")
        assert store.db_path is None


# ---------------------------------------------------------------------------
# Full round-trip with local SQLite (existing behavior preserved)
# ---------------------------------------------------------------------------


class TestLocalRoundTrip:
    """Verify the entire init/load/query cycle still works through new constructor."""

    def test_init_and_stats(self, tmp_path):
        db = tmp_path / "roundtrip.db"
        store = DregsStore(str(db))
        store.init()
        stats = store.stats()
        assert stats["total_triples"] == 0
        assert stats["version"] == "0.1.0"
        store.close()

    def test_init_with_schema(self, tmp_path):
        examples = Path(__file__).parent.parent / "examples"
        ontology = examples / "ontology.ttl"
        shapes = examples / "shapes.ttl"

        db = tmp_path / "roundtrip.db"
        store = DregsStore(str(db))
        result = store.init(schema_path=ontology, shacl_path=shapes)
        assert result["schema_triples"] > 0
        assert result["shacl_triples"] > 0
        store.close()

    def test_dsn_env_var_local_round_trip(self, tmp_path, monkeypatch):
        """DregsStore() with DREGS_DSN pointing to a file should work end to end."""
        db = tmp_path / "envvar.db"
        monkeypatch.setenv("DREGS_DSN", str(db))

        store = DregsStore()
        store.init()
        stats = store.stats()
        assert stats["total_triples"] == 0
        store.close()


# ---------------------------------------------------------------------------
# CLI: optional DB argument
# ---------------------------------------------------------------------------


class TestCLIOptionalDB:
    """CLI commands should work without DB arg when DREGS_DSN is set."""

    def test_init_with_env_dsn(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from dregs.cli import cli

        db = tmp_path / "cli_env.db"
        monkeypatch.setenv("DREGS_DSN", str(db))

        runner = CliRunner()
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0, result.output
        assert "Initialized" in result.output

    def test_init_explicit_db_still_works(self, tmp_path):
        from click.testing import CliRunner
        from dregs.cli import cli

        db = tmp_path / "explicit.db"
        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--db", str(db)])
        assert result.exit_code == 0, result.output
        assert "Initialized" in result.output

    def test_init_no_db_no_env_fails(self, monkeypatch):
        from click.testing import CliRunner
        from dregs.cli import cli

        monkeypatch.delenv("DREGS_DSN", raising=False)
        runner = CliRunner()
        result = runner.invoke(cli, ["init"])
        assert result.exit_code != 0

    def test_info_with_env_dsn(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from dregs.cli import cli

        db = tmp_path / "cli_info.db"
        # First init
        store = DregsStore(str(db))
        store.init()
        store.close()

        monkeypatch.setenv("DREGS_DSN", str(db))
        runner = CliRunner()
        result = runner.invoke(cli, ["info"])
        assert result.exit_code == 0, result.output
        assert "Triples" in result.output

    def test_graphs_with_env_dsn(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from dregs.cli import cli

        db = tmp_path / "cli_graphs.db"
        store = DregsStore(str(db))
        store.init()
        store.close()

        monkeypatch.setenv("DREGS_DSN", str(db))
        runner = CliRunner()
        result = runner.invoke(cli, ["graphs"])
        assert result.exit_code == 0, result.output
