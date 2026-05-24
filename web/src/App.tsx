import { BrowserRouter, Routes, Route } from "react-router-dom";
import { ThemeProvider } from "./design/ThemeContext";
import Layout from "./components/Layout";
import Chat from "./components/Chat";
import Admin from "./pages/Admin";
import Dashboard from "./pages/Dashboard";
import Tasks from "./pages/Tasks";
import Monitors from "./pages/Monitors";
import Routines from "./pages/Routines";
import CodeSessions from "./pages/CodeSessions";
import Settings from "./pages/Settings";
import IDEPage from "./pages/IDE";

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="chat" element={<Chat />} />
            <Route path="admin" element={<Admin />} />
            <Route path="tasks" element={<Tasks />} />
            <Route path="monitors" element={<Monitors />} />
            <Route path="routines" element={<Routines />} />
            <Route path="code" element={<CodeSessions />} />
            <Route path="ide" element={<IDEPage />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}
