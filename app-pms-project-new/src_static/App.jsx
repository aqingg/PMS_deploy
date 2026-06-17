import React, { Component } from 'react';
import axios from "axios";
import Header from './components/Header';
import Menu from './components/Menu';
import { Splitter, Card } from 'antd';
import { HashRouter, Routes, Route, Navigate } from "react-router-dom";

import EditPage from './components/pages/EditPage';
import TaskDetailPage from './components/pages/TaskDetailPage';

import './App.css';

export default class App extends Component {
  constructor(props) {
    super(props);
    this.state = {
      user: { username: "Unknown", department: "Unknown" },
      projectName: "Dummy Project",
      loading: true,
    };
  }

 componentDidMount() {
  // 读取 project 名
  const params = new URLSearchParams(window.location.search);
  const projectFromUrl = params.get("project");

  console.log("项目名 =", projectFromUrl);
  this.setState({ projectName: projectFromUrl || null });

  // ⭐ 使用 FAKE DATA 替代 axios 请求
  const fakeUserInfo = {
    machine_id: "DemoUser001",
    department: "R&D Test Department"
  };

  // 模拟网络延迟（可选）
  setTimeout(() => {
    this.setState({
      user: { 
        username: fakeUserInfo.machine_id, 
        department: fakeUserInfo.department 
      },
      loading: false
    });
  }, 300);
}


  render() {
    const { user, projectName, loading } = this.state;

    if (loading) return <div>Authorizing...</div>;

    return (
      <HashRouter>
        <div style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
          <div className="header-container">
            {/* ⭐ 传入 user */}
            <Header user={user} projectName={projectName} />
          </div>

          <div className="content-wrapper">
            <Splitter style={{ height: "100%", width: "100%" }}>
              <Splitter.Panel
                defaultSize={300}
                min={200}
                max={500}
                style={{ overflow: "auto", background: "#f5f5f5" }}
              >
                {/* ⭐ 传入 user + projectName */}
                <Menu user={user} projectName={projectName} />
              </Splitter.Panel>

              <Splitter.Panel style={{ padding: 8, background: "#f0f2f5" }}>
                <Card 
                  size="small"
                  bordered={false}
                  style={{
                    height: "100%",
                    boxShadow: "0 1px 2px rgba(0,0,0,0.08)",
                    borderRadius: 4
                  }}
                >
                  <Routes>
                    {/* 默认跳到 edit 页面 */}
                    <Route 
                      path="/" 
                      element={<Navigate to="/edit" replace />} 
                    />

                    {/* ⭐ EditPage 接收到 user & projectName */}
                    <Route 
                      path="/edit" 
                      element={<EditPage user={user} projectName={projectName} />} 
                    />

                    {/* ⭐ TaskDetail 接收到 user & projectName */}
                    <Route 
                      path="/task/:taskName" 
                      element={<TaskDetailPage user={user} projectName={projectName} />} 
                    />
                  </Routes>
                </Card>
              </Splitter.Panel>

            </Splitter>
          </div>
        </div>
      </HashRouter>
    );
  }
}
