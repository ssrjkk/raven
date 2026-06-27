import { z } from "zod";

export const schema = z.object({
  issueNumber: z.number().describe("Issue number to triage"),
  label: z.string().describe("Label to apply"),
  assignee: z.string().optional().describe("GitHub username to assign"),
});

export const handler = async (input: z.infer<typeof schema>) => {
  const { issueNumber, label, assignee } = input;
  const token = process.env.GITHUB_TOKEN;
  const headers = {
    Accept: "application/vnd.github.v3+json",
    Authorization: `Bearer ${token}`,
  };

  await fetch(
    `https://api.github.com/repos/ssrjkk/raven/issues/${issueNumber}/labels`,
    { method: "POST", headers, body: JSON.stringify({ labels: [label] }) }
  );

  if (assignee) {
    await fetch(
      `https://api.github.com/repos/ssrjkk/raven/issues/${issueNumber}/assignees`,
      { method: "POST", headers, body: JSON.stringify({ assignees: [assignee] }) }
    );
  }

  return { ok: true, issue: issueNumber, label, assignee };
};
