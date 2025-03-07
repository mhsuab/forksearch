from types import FunctionType
from database import GitDB
from gh_utils import *
from rich import print, table
from typer import confirm as Confirm

HOST = "localhost"
BOLTPORT = 7687
USERNAME = 'neo4j'
PASSWORD = 'password'

def init_db():
    return GitDB(HOST, BOLTPORT, USERNAME, PASSWORD)

def print_info(gh_info, db_info, owner, repo):
    if gh_info['isFork']:
        caption = f"Fork from [bold red]{gh_info['parent']['nameWithOwner']}[/bold red]"
    else:
        caption = ""

    # print info in table
    t = table.Table(title=f'Repository {owner}/{repo}', caption=caption)
    t.add_column("", justify="right", style="cyan", no_wrap=True)
    t.add_column("Database", justify="right", no_wrap=True)
    t.add_column("Github", justify="right", no_wrap=True)
    t.add_column("Percentage (%)", justify="right", no_wrap=True)

    t.add_row(
        "Watchers",
        str(db_info['watchers']),
        str(gh_info['watchers']['totalCount']),
        f"{db_info['watchers']/gh_info['watchers']['totalCount'] * 100:.1f}" if gh_info['watchers']['totalCount'] else "N/A",
        style="cyan"
    )
    t.add_row(
        "Forks",
        str(db_info['forks']),
        str(gh_info['forkCount']),
        f"{db_info['forks']/gh_info['forkCount'] * 100:.1f}" if gh_info['forkCount'] else "N/A",
        style="green"
    )
    t.add_row(
        "Stargazers",
        str(db_info['stargazers']),
        str(gh_info['stargazerCount']),
        f"{db_info['stargazers']/gh_info['stargazerCount'] * 100:.1f}" if gh_info['stargazerCount'] else "N/A",
        style="magenta"
    )

    print (t)
    print ()

def query_info(endpoint: RequestsEndpoint, db: GitDB, owner: str, name: str):
    gh_info = query_repo_info(endpoint, owner=owner, name=name)

    needed_field = ['isFork', 'url', 'name']
    repo_properties = {k: gh_info[k] for k in needed_field}

    db_info = db.get_repo_info(id=gh_info['id'], login=owner, owner=gh_info['owner'], repo_properties=repo_properties)

    return gh_info, db_info

def query_all(endpoint: RequestsEndpoint, db: GitDB, owner: str, name: str, db_info: dict, id: str):
    print (f"Querying all watchers, forks, and stargazers for [italic blue]{owner}/{name}[/italic blue]...")

    has_next_page = True

    # initialize watchers/forks/stargazers counts
    counts = {
        'watchers': db_info['watchers'],
        'forks': db_info['forks'],
        'stargazers': db_info['stargazers'],
    }

    # initialize cursor from db_info
    cursors = {
        'watchers': db_info['watcher_cursor'],
        'forks': db_info['fork_cursor'],
        'stargazers': db_info['stargazer_cursor'],
    }

    while has_next_page:
        op = Operation(schema.Query)
        r = op.repository(owner=owner, name=name, __alias__=camel_case(name))
        r.__fields__(id=True)
        select_watchers(r, after=cursors['watchers'])
        select_forks(r, after=cursors['forks'])
        select_stargazers(r, after=cursors['stargazers'])

        p = query_with_retry(endpoint, op)

        data = p['data'][camel_case(name)]

        # add all edged in database
        result = db.add_all_edges(data)

        # get all length of nodes
        watchers_len = len(data['watchers']['nodes'])
        forks_len = len(data['forks']['nodes'])
        stargazers_len = len(data['stargazers']['nodes'])

        # update counts
        counts['watchers'] += watchers_len
        counts['forks'] += forks_len
        counts['stargazers'] += stargazers_len

        # print count of watchers/forks/stargazers
        print(f"Watchers: {counts['watchers']}, Forks: {counts['forks']}, Stargazers: {counts['stargazers']} ({len(result)} edges added)")

        # update has_next_page if any of the page has next page
        has_next_page = data['watchers']['pageInfo']['hasNextPage'] \
            or data['forks']['pageInfo']['hasNextPage'] \
            or data['stargazers']['pageInfo']['hasNextPage']

        if watchers_len > 0:
            cursors['watchers'] = data['watchers']['pageInfo']['endCursor']
        if forks_len > 0:
            cursors['forks'] = data['forks']['pageInfo']['endCursor']
        if stargazers_len > 0:
            cursors['stargazers'] = data['stargazers']['pageInfo']['endCursor']

def request_repo(endpoint: RequestsEndpoint, db: GitDB, owner: str, name: str, info: FunctionType = print_info, is_recursive: bool = False, do_request: bool = False):
    gh_info, db_info = query_info(endpoint = endpoint, db = db, owner = owner, name = name)

    info(gh_info, db_info, owner, name)

    if gh_info['isFork']:
        if is_recursive:
            parent_owner, parent_name = gh_info['parent']['nameWithOwner'].split('/')
            request_repo(endpoint, db, parent_owner, parent_name, info, is_recursive, do_request)
            info(gh_info, db_info, owner, name)

        elif Confirm("Do you want to request parent repo?"):
            parent_owner, parent_name = gh_info['parent']['nameWithOwner'].split('/')

            request_repo(endpoint, db, parent_owner, parent_name, info, is_recursive, do_request)
            info(gh_info, db_info, owner, name)

    if do_request or Confirm("Do you want to query all data?"):
        query_all(endpoint, db, owner, name, db_info, gh_info['id'])

    gh_info, db_info = query_info(endpoint = endpoint, db = db, owner = owner, name = name)
    info(gh_info, db_info, owner, name)
