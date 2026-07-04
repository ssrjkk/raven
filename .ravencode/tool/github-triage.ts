import { z } from "zod";

export const schema = z.object({
  issueNumber: z.number().describe("Issue number to triage"),
  label: z.string().describe("Label to apply"),
  assignee: z.string().optional().describe("GitHub username to assign"),
});

export const handler = async (input: z.infer<typeof schema>) => {
  const { issueNumber, label, assignee } = input;
  const token = process.env.GITHUB_TOKEN;
  if (!token) throw new Error("GITHUB_TOKEN not set");
  const headers = {
    Accept: "application/vnd.github.v3+json",
    Authorization: `Bearer ${token}`,
  };

  const labelRes = await fetch(
    `https://api.github.com/repos/ssrjkk/raven/issues/${issueNumber}/labels`,
    { method: "POST", headers, body: JSON.stringify({ labels: [label] }) }
  );
  if (!labelRes.ok) throw new Error(`GitHub label API error: ${labelRes.status} ${await labelRes.text()}`);

  if (assignee) {
    const assignRes = await fetch(
      `https://api.github.com/repos/ssrjkk/raven/issues/${issueNumber}/assignees`,
      { method: "POST", headers, body: JSON.stringify({ assignees: [assignee] }) }
    );
    if (!assignRes.ok) throw new Error(`GitHub assign API error: ${assignRes.status} ${await assignRes.text()}`);
  }

  return { ok: true, issue: issueNumber, label, assignee };
};
