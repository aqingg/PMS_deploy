import React from "react";
import { HashRouter, Routes, Route, Navigate } from "react-router-dom";
import { Splitter, Card, Modal, Select, Button } from "antd";

import Header from "./components/Header";
import Menu from "./components/Menu";
import EditPage from "./components/pages/EditPage";
import TaskDetailPage from "./components/pages/TaskDetailPage";

import { useAppContext } from "./context/AppContext";
import "./App.css";

export default function App() {
  const {
    user,
    projectName,
    needCreate,
    selectableDepartments,
    selectedDepartment,
    setSelectedDepartment,
    createProject,
  } = useAppContext();

  return (
    <HashRouter>
      {/* ⭐ 外层容器（恢复旧 UI 的关键） */}
      <div style={{ height: "100vh" }}>
        {/* ⭐ 实际布局容器（旧代码结构） */}
        <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
          
          {/* Header */}
          <div className="header-container">
            <Header user={user} projectName={projectName} />
          </div>

          {/* 内容区 */}
          <div className="content-wrapper">
            <Splitter style={{ height: "100%", width: "100%" }}>
              {/* 左侧菜单 */}
              <Splitter.Panel
                defaultSize={350}
                min={200}
                max={500}
                style={{ overflow: "auto", background: "#f5f5f5" }}
              >
                <Menu />
              </Splitter.Panel>

              {/* 右侧内容区 */}
              <Splitter.Panel style={{ padding: 8, background: "#f0f2f5" }}>
                <Card
                  size="small"
                  bordered={false}
                  style={{
                    height: "100%",
                    boxShadow: "0 1px 2px rgba(0,0,0,0.08)",
                    borderRadius: 4,
                  }}
                >
                  <Routes>
                    <Route path="/" element={<Navigate to="/edit" replace />} />
                    <Route path="/edit" element={<EditPage />} />
                    <Route path="/task/:projectId/:taskId" element={<TaskDetailPage />} />
                  </Routes>
                </Card>
              </Splitter.Panel>
            </Splitter>
          </div>
        </div>
      </div>

      {/* 创建项目弹窗 */}
      <Modal
        open={needCreate}
        title="请选择项目所属部门"
        footer={null}
        closable={false}
        getContainer={false}   // ⭐ 加这一行！
      >
        <p>当前项目不存在，请从模板中选择一个部门并创建项目：</p>

        <Select
          style={{ width: "100%", marginTop: 10 }}
          placeholder="请选择部门"
          value={selectedDepartment}
          onChange={setSelectedDepartment}
        >
          {selectableDepartments.map((dept) => (
            <Select.Option key={dept} value={dept}>
              {dept}
            </Select.Option>
          ))}
        </Select>

        <Button
          type="primary"
          block
          style={{ marginTop: 20 }}
          disabled={!selectedDepartment}
          onClick={createProject}
        >
          确定创建项目
        </Button>
      </Modal>
    </HashRouter>
  );
}
