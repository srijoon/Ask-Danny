# flask CLI commands for ops and testing: init-db (collections + Atlas indexes),
# create-user, ingest (bulk-load local files) and ask (run the RAG pipeline as a
# given user). They call the same services as the web routes.
import os

import click
from flask import current_app

from .auth.users import UserError, create_user
from .db import USERS, ensure_indexes, get_db, search_index_status
from .ingestion.service import IngestionError, ingest_document
from .permissions import document_access, principals_for


def init_app(app):
    """Register all four commands on the flask CLI (called by create_app)."""
    for command in (init_db, create_user_command, ingest, ask):
        app.cli.add_command(command)


@click.command("init-db")
def init_db():
    """Create collections and indexes — runs ensure_indexes() from db.py."""
    ensure_indexes(get_db(), current_app.config, echo=click.echo)
    # indexes build asynchronously on Atlas; show where they stand right now
    click.echo(f"Search index status: {search_index_status(get_db(), current_app.config)}")


@click.command("create-user")
@click.argument("username")
@click.option("--groups", default="", help="Comma-separated groups, e.g. hr,finance.")
@click.option("--admin", is_flag=True, help="Can upload documents and manage users.")
@click.password_option()
def create_user_command(username, groups, admin, password):
    """Create a user — same create_user() the admin page calls."""
    try:
        user = create_user(get_db(), username, password, groups=groups, is_admin=admin)
    except UserError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Created {'admin ' if admin else ''}user '{user['username']}' groups={user['groups']}")


@click.command("ingest")
@click.argument("paths", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--groups", default="", help="Comma-separated groups that can see the documents.")
@click.option("--everyone", is_flag=True, help="Visible to every signed-in user.")
@click.option("--title", default=None, help="Title (only with a single file).")
def ingest(paths, groups, everyone, title):
    """Bulk-load local files — same ingest_document() the upload routes call."""
    access = document_access([groups], everyone=everyone)
    if not access:
        raise click.UsageError("Pass --groups or --everyone.")
    for path in paths:
        with open(path, "rb") as fh:
            data = fh.read()
        try:
            # same pipeline as the upload endpoints; "cli" marks bulk-loaded docs
            doc = ingest_document(os.path.basename(path), data, access=access, uploaded_by="cli",
                                  title=title if len(paths) == 1 else None)
            click.echo(f"OK   {path}: {doc['chunk_count']} chunks")
        except IngestionError as exc:
            click.echo(f"SKIP {path}: {exc}", err=True)


@click.command("ask")
@click.argument("question")
@click.option("--user", "username", required=True, help="Answer with this user's permissions.")
def ask(question, username):
    """Run the full RAG pipeline as a chosen user — same answer_question() the routes use."""
    # importing here keeps the answer/retrieval chain out of `flask --help` startup
    from .chat.answer import answer_question

    user = get_db()[USERS].find_one({"username": username.lower()})
    if not user:
        raise click.ClickException(f"No user '{username}'.")
    answer = answer_question(question, [], principals_for(user))
    click.echo(f"[{answer.status}] mode={answer.retrieval_mode} llm_calls={answer.llm_calls}\n")
    click.echo(answer.text)
    for source in answer.sources:
        page = f" p.{source['page']}" if source["page"] else ""
        click.echo(f"  [{source['n']}] {source['title']}{page} (score {source['score']})")
