# Dev workflow (managed by setup-dev-workflow.sh)
case $- in *i*) ;; *) return ;; esac

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
export PROJECTS_DIR="${PROJECTS_DIR:-$HOME/projects}"

command -v starship >/dev/null 2>&1 && eval "$(starship init bash)"
command -v fzf      >/dev/null 2>&1 && eval "$(fzf --bash 2>/dev/null)"
command -v zoxide   >/dev/null 2>&1 && eval "$(zoxide init bash)"

export FZF_DEFAULT_COMMAND='fd --type f --hidden --exclude .git'
export FZF_CTRL_T_COMMAND="$FZF_DEFAULT_COMMAND"
export FZF_DEFAULT_OPTS='--height 40% --layout=reverse --border'

# nicer defaults
command -v eza >/dev/null 2>&1 && {
  alias ls='eza --group-directories-first'
  alias ll='eza -lah --git --group-directories-first'
  alias tree='eza --tree --level=3'
}
command -v bat >/dev/null 2>&1 && alias cat='bat --paging=never'

# tools
alias lg='lazygit'
alias ld='lazydocker'
alias d='dev'
alias gs='git status -sb'
alias gl='git lg'

# pick a project (any git repo under $PROJECTS_DIR) and open its Zellij session
p() {
  local dir
  dir="$(fd -H -t d '^\.git$' "$PROJECTS_DIR" --max-depth 3 -x dirname {} 2>/dev/null | sort | fzf --prompt='project> ')" || return
  zdev "$dir"
}

# commit with the Jira key from the branch name: gcm "fix thing" -> "PROJ-123: fix thing"
gcm() {
  local key
  key="$(git branch --show-current | grep -oE '[A-Z][A-Z0-9]+-[0-9]+' | head -1)"
  if [[ -n "$key" ]]; then git commit -m "$key: $*"; else git commit -m "$*"; fi
}

# new worktree for a branch (reviews without stashing): gwt feature/PROJ-1-x
gwt() {
  local b="${1:?usage: gwt <branch>}" r dir
  r="$(basename "$(git rev-parse --show-toplevel)")"
  dir="../$r-${b//\//-}"
  git worktree add "$dir" "$b" 2>/dev/null || git worktree add -b "$b" "$dir"
  cd "$dir" || return
}

# fuzzy checkout of a local/remote branch
gco() {
  local b
  b="$(git branch --all --sort=-committerdate --format='%(refname:short)' | sed 's#^origin/##' | awk '!s[$0]++' | fzf --prompt='branch> ')" || return
  git switch "$b"
}
