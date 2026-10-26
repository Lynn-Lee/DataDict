import { createBrowserRouter, Navigate } from "react-router-dom";

import RequireAuth from "@/components/RequireAuth";
import AppLayout from "@/layouts/AppLayout";
import LoginPage from "@/pages/LoginPage";
import NotFoundPage from "@/pages/NotFoundPage";
import StandardFieldsPage from "@/pages/StandardFieldsPage";
import StandardLibraryPage from "@/pages/StandardLibraryPage";
import TableDetailPage from "@/pages/TableDetailPage";
import TablesPage from "@/pages/TablesPage";

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    path: "/",
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/standard-library" replace /> },
      { path: "tables", element: <TablesPage /> },
      { path: "tables/:urn", element: <TableDetailPage /> },
      { path: "standard-fields", element: <StandardFieldsPage /> },
      { path: "standard-library", element: <StandardLibraryPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
