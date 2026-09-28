import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
from dispatchledger.models import Base
target_metadata = Base.metadata


# --- where to connect -------------------------------------------------------
#
# alembic.ini carries a local development URL, which is convenient and is also
# the only database this project could migrate until this block existed: the
# ini value is committed, so `alembic upgrade head` always went to localhost no
# matter what the environment said.
#
# The failure was quiet, which is what made it worth fixing properly. Pointed
# at a fresh managed database, Alembic read the local one instead, found it
# already at head, printed nothing and exited 0. A successful-looking run that
# created nothing.
#
# DATABASE_URL now wins when it is set, and the ini remains the local default.
#
# The %-escaping is not decoration: alembic.ini is a ConfigParser file, so
# set_main_option runs %-interpolation over the value. A password containing a
# literal % -- which managed providers do generate -- would otherwise raise an
# interpolation error, or worse, silently mangle the credential.
def _configured_url() -> str | None:
    url = os.environ.get("DATABASE_URL")
    return url.replace("%", "%%") if url else None


_url = _configured_url()
if _url:
    config.set_main_option("sqlalchemy.url", _url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Say out loud which host is about to be migrated. A migration run is
        # one of the few operations that cannot be undone by re-running it,
        # and "I thought it was pointed somewhere else" is the way that goes
        # wrong. The password is stripped -- this line ends up in CI logs.
        url = connectable.url
        print(f"alembic: migrating {url.host or 'local'}/{url.database} as {url.username}")

        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
