// Repository links, shared by every page (one place to change the URL).
export const REPO = "https://github.com/Vinit230606/ipl-win-probability";

export function linkRepo() {
  document.querySelectorAll("a.repo-link").forEach((a) => { a.href = REPO; });
  document.querySelectorAll("a.repo-file[data-path]").forEach((a) => {
    const p = a.dataset.path;
    a.href = `${REPO}/${p.includes(".") ? "blob" : "tree"}/main/${p}`;
  });
}
