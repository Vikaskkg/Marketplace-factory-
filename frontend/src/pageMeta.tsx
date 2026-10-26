import { useEffect, type ReactNode } from "react";

export const PAGES = {
  marketplace: ["Marketplace", "Search agents, models, MCP servers, knowledge bases and guardrails across all your Azure AI Foundry projects."],
  factory: ["Agent Factory", "Create an agent: choose a model, write its instructions, attach tools and knowledge, and review its risk and guardrail."],
  guardrails: ["Guardrails", "Content-filter policies that screen prompts and completions. Review existing ones or create your own."],
  evals: ["Evaluations", "Test each agent against quality and safety checks, see the results over time, and know which agents are ready to release."],
  playground: ["Playground", "Try a model or an agent interactively. A good place to test how a guardrail behaves."],
} as const;
export type PageKey = keyof typeof PAGES;

export function PageHeader({ page, children }: { page: PageKey; children?: ReactNode }) {
  useEffect(() => { document.title = `${PAGES[page][0]} · Agent Hub`; }, [page]);
  return (
    <header>
      <h1>{PAGES[page][0]}</h1>
      <p className="sub">{PAGES[page][1]}</p>
      {children}
    </header>
  );
}
