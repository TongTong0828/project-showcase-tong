import { useMemo, useState } from "react";

import { createWorkbenchClient } from "./api/client";
import { Shell, type RouteId } from "./components/Shell";
import { ProjectProvider } from "./context/ProjectContext";
import { I18nProvider } from "./i18n";
import { AskPage } from "./pages/AskPage";
import { ComparePage } from "./pages/ComparePage";
import { DiscoverPage } from "./pages/DiscoverPage";
import { HealthPage } from "./pages/HealthPage";
import { LibraryPage } from "./pages/LibraryPage";
import { OverviewPage } from "./pages/OverviewPage";
import { SearchPage } from "./pages/SearchPage";
import { WorkspacePage } from "./pages/WorkspacePage";

export function App() {
  const [route, setRoute] = useState<RouteId>("overview");
  const client = useMemo(() => createWorkbenchClient(), []);

  return (
    <I18nProvider>
      <ProjectProvider client={client}>
        <Shell active={route} onNavigate={setRoute}>
          {route === "workspace" ? <WorkspacePage /> : null}
          {route === "compare" ? <ComparePage client={client} /> : null}
          {route === "health" ? <HealthPage client={client} /> : null}
          {route === "library" ? <LibraryPage client={client} /> : null}
          {route === "search" ? <SearchPage client={client} /> : null}
          {route === "ask" ? <AskPage client={client} /> : null}
          {route === "discover" ? <DiscoverPage client={client} /> : null}
          {route === "overview" ? <OverviewPage client={client} /> : null}
        </Shell>
      </ProjectProvider>
    </I18nProvider>
  );
}
