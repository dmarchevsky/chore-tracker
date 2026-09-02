# Shared helpers for the backup/restore scripts. Sourced, never executed.
#
# Style follows /usr/local/bin/backup-to-truenas.sh on this host: timestamped log lines on
# stdout, everything fatal goes through die() so a half-finished run cannot look like a
# successful one.

_ts()  { date '+%Y-%m-%d %H:%M:%S'; }
log()  { printf '%s  INFO   %s\n' "$(_ts)" "$*"; }
warn() { printf '%s  WARN   %s\n' "$(_ts)" "$*" >&2; }
die()  { printf '%s  ERROR  %s\n' "$(_ts)" "$*" >&2; exit 1; }

# The two stacks are separate compose projects with separate volumes (CLAUDE.md). Naming the
# compose invocation per stack is what keeps a backup of one from ever touching the other.
compose_for() {
    case "$1" in
        prod) printf 'docker compose -f docker-compose.prod.yml --env-file env.production' ;;
        dev)  printf 'docker compose' ;;
        *)    die "unknown stack '$1' — expected 'prod' or 'dev'" ;;
    esac
}

# Database user/name. Dev pins them as literals in docker-compose.yml; prod takes them from
# env.production, which defaults the same way the compose file does (${DB_USER:-chore}).
_env_production() {
    [[ -f env.production ]] || return 0
    grep -E "^$1=" env.production | tail -1 | cut -d= -f2- | tr -d '[:space:]'
}
db_user_for() {
    local v=""
    [[ "$1" == "prod" ]] && v="$(_env_production DB_USER)"
    printf '%s' "${v:-chore}"
}
db_name_for() {
    local v=""
    [[ "$1" == "prod" ]] && v="$(_env_production DB_NAME)"
    printf '%s' "${v:-chore}"
}

require_db_running() {
    local stack="$1" cmp
    cmp="$(compose_for "$stack")"
    # `ps -q db` prints an id only when the container exists AND is running.
    [[ -n "$($cmp ps -q db 2>/dev/null)" ]] \
        || die "the '$stack' stack's db is not running — start it first ($([[ $stack == prod ]] && echo 'just prod-up' || echo 'just up'))"
}

# Row counts + per-child balances: the numbers a restore has to reproduce exactly (spec §14).
# Balance is sum(amount_cents) per child, which is what ledger.balance_cents() computes.
COUNT_SQL="
select json_build_object(
  'users',             (select count(*) from users),
  'chores',            (select count(*) from chores),
  'chore_occurrences', (select count(*) from chore_occurrences),
  'ledger_entries',    (select count(*) from ledger_entries),
  'submissions',       (select count(*) from submissions),
  'balances',          (select coalesce(json_object_agg(username, cents), '{}'::json) from (
                          select u.username, coalesce(sum(l.amount_cents), 0) as cents
                          from users u left join ledger_entries l on l.child_id = u.id
                          where u.role = 'child' group by u.username) b)
);"
