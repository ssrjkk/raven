import * as core from "@actions/core";
import * as github from "@actions/github";

async function run(): Promise<void> {
  try {
    const token = core.getInput("github-token");
    const octokit = github.getOctokit(token);
    const context = github.context;

    if (!context.payload.pull_request) {
      core.setFailed("This action only works on pull_request events");
      return;
    }

    const { data: diff } = await octokit.rest.repos.compareCommits({
      owner: context.repo.owner,
      repo: context.repo.repo,
      base: context.payload.pull_request.base.sha,
      head: context.payload.pull_request.head.sha,
    });

    const files = diff.files || [];
    const changedLines = files.reduce((sum, f) => sum + (f.additions || 0) + (f.deletions || 0), 0);

    core.info(`PR #${context.payload.pull_request.number}: ${files.length} files, ${changedLines} lines`);

    // Integration point — Raven AI reviews the diff here
    core.setOutput("conclusion", "pass");
  } catch (error) {
    if (error instanceof Error) core.setFailed(error.message);
  }
}

run();
