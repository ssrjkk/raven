import { z } from "zod";

export const schema = z.object({
  query: z.string().describe("Search query for pull requests"),
  state: z.enum(["open", "closed", "merged"]).optional().default("open"),
  limit: z.number().optional().default(10),
});

export const handler = async (input: z.infer<typeof schema>) => {
  const { query, state, limit } = input;
  const q = `is:pr is:${state} ${query} repo:ssrjkk/raven`;
  const url = `https://api.github.com/search/issues?q=${encodeURIComponent(q)}&per_page=${limit}`;
  const res = await fetch(url, {
    headers: { Accept: "application/vnd.github.v3+json" },
  });
  const data = await res.json();
  return data.items.map((item: any) => ({
    number: item.number,
    title: item.title,
    state: item.state,
    author: item.user?.login,
    url: item.html_url,
    created: item.created_at,
  }));
};
