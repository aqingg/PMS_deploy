// App.jsx
import React, { useContext } from "react";
import { Splitter } from "antd";

import Header from "./components/Header";
import ProjectSummary from "./components/ProjectSummary";
import ToDoList from "./components/ToDoList";
import SearchBar from "./components/SearchBar";

import { AppProvider, AppContext } from "./context/AppContext";
import "./App.css";

// ====================================================
// Layout（只负责布局 & Context 消费）
// ====================================================
function AppLayout() {
  const { user, loading } = useContext(AppContext);

  if (loading) {
    return <div>Authorizing...</div>;
  }

  return (
    <div
      style={{
        height: "100vh",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Header */}
      <div className="header-container">
        <Header user={user || { username: "", department: "" }} />
      </div>

      {/* Main Content */}
      <div style={{ flex: "1 1 auto", minHeight: 0 }}>
        <Splitter style={{ height: "100%" }}>
          {/* Left: Todo */}
          <Splitter.Panel defaultSize="50%" min="40%" max="80%">
      <div
        style={{
          height: "100%",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {/* Search Bar */}
        <div>
          <SearchBar />
        </div>

        {/* Divider */}
        <div style={{ padding: "0 12px" }}>
          <div
            style={{
              borderTop: "1px solid #f0f0f0",
              margin: "8px 0",
            }}
          />
        </div>

        {/* Todo List */}
        <div style={{ flex: "1 1 auto", minHeight: 0 }}>
          <ToDoList />
        </div>
      </div>
          </Splitter.Panel>

          {/* Right: Project Summary */}
          <Splitter.Panel>
            <div
              style={{
                height: "100%",
                overflow: "hidden",
                paddingLeft: 10,
              }}
            >
              <ProjectSummary />
            </div>
          </Splitter.Panel>
        </Splitter>
      </div>
    </div>
  );
}

// ====================================================
// App Root
// ====================================================
export default function App() {
  return (
    <AppProvider>
      <AppLayout />
    </AppProvider>
  );
}
