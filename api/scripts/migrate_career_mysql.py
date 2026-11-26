"""Apply the existing career MySQL migrations using Python."""

import argparse
import asyncio
import re
from pathlib import Path
from time import monotonic
from zlib import crc32

import aiomysql
from pymysql.constants import CLIENT

from app.config import settings

HISTORY = """
    CREATE TABLE IF NOT EXISTS flyway_schema_history (
        installed_rank INT NOT NULL PRIMARY KEY,
        version VARCHAR(50),
        description VARCHAR(200) NOT NULL,
        type VARCHAR(20) NOT NULL,
        script VARCHAR(1000) NOT NULL,
        checksum INT,
        installed_by VARCHAR(100) NOT NULL,
        installed_on TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        execution_time INT NOT NULL,
        success BOOLEAN NOT NULL,
        INDEX flyway_schema_history_s_idx (success)
    ) ENGINE=InnoDB
"""


def checksum(sql: str) -> int:
    value = 0
    for line in sql.splitlines():
        value = crc32(line.encode("utf-8"), value)
    return value if value < 2**31 else value - 2**32


async def migrate(directory: Path) -> None:
    if not settings.career_mysql_host:
        raise RuntimeError("Set CAREER_MYSQL_HOST before running the migration")
    password = settings.career_mysql_password.get_secret_value()
    if not password:
        raise RuntimeError("缺少 CAREER_MYSQL_PASSWORD。请在项目根目录的 .env 配置 MySQL 密码后再运行迁移。")
    migrations = sorted(
        (int(match[1]), path)
        for path in directory.iterdir()
        if path.is_file() and (match := re.fullmatch(r"V(\d+)__.*\.sql", path.name))
    )
    if [version for version, _ in migrations] != list(range(1, 21)):
        raise RuntimeError("Expected career migrations V1–V20")
    db = await aiomysql.connect(
        host=settings.career_mysql_host, port=settings.career_mysql_port,
        user=settings.career_mysql_user, password=password,
        db=settings.career_mysql_database, charset="utf8mb4", autocommit=True,
        init_command="SET time_zone = '+00:00'", client_flag=CLIENT.MULTI_STATEMENTS,
    )
    try:
        async with db.cursor() as cursor:
            await cursor.execute("SELECT GET_LOCK(CONCAT(DATABASE(), ':career_migrations'), 10)")
            if (await cursor.fetchone())[0] != 1:
                raise RuntimeError("Could not lock career migrations")
            await cursor.execute(HISTORY)
            await cursor.execute("""
                SELECT installed_rank, version, script, checksum, success
                FROM flyway_schema_history ORDER BY installed_rank
            """)
            history = await cursor.fetchall()
            if any(not row[4] for row in history):
                raise RuntimeError("Career schema has a failed migration; reconcile it before retrying")
            installed = {row[1]: (row[2], row[3]) for row in history if row[1] is not None}
            if set(installed) - {str(version) for version, _ in migrations}:
                raise RuntimeError("Career schema has versions outside this release")
            # Validate every recorded checksum before performing any migration writes.
            pending = []
            for version, path in migrations:
                sql = path.read_text(encoding="utf-8-sig")
                signature = (path.name, checksum(sql))
                if str(version) in installed:
                    if installed[str(version)] != signature:
                        raise RuntimeError(f"Career migration history disagrees with {path.name}")
                else:
                    pending.append((version, path, sql, signature[1]))
            if pending and any(int(version) > pending[0][0] for version in installed):
                raise RuntimeError("Career schema has a gap in applied versions")
            rank = max((row[0] for row in history), default=0)
            for version, path, sql, digest in pending:
                rank += 1
                started = monotonic()
                await cursor.execute("""
                    INSERT INTO flyway_schema_history
                        (installed_rank, version, description, type, script, checksum,
                         installed_by, execution_time, success)
                    VALUES (%s, %s, %s, 'SQL', %s, %s, SUBSTRING_INDEX(CURRENT_USER(), '@', 1), 0, 0)
                """, (rank, str(version), path.stem.split("__", 1)[1].replace("_", " "), path.name, digest))
                await cursor.execute(sql)
                while await cursor.nextset():
                    pass
                await cursor.execute("""
                    UPDATE flyway_schema_history SET success = 1, execution_time = %s
                    WHERE installed_rank = %s
                """, (int((monotonic() - started) * 1000), rank))
                print(f"Applied {path.name}")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=(
        Path(__file__).resolve().parents[2] / "backend" / "src" / "main" / "resources" / "db" / "migration"
    ))
    asyncio.run(migrate(parser.parse_args().directory))
