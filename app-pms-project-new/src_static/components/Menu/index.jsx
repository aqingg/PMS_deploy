import React from 'react';
import { Card } from 'antd';
import ProjectInfo from './ProjectInfo';
import Progress from './Progress';
import './index.css';

export default function Menu({ user, projectName }) {  // ⭐ 接收两个 props
  return (
    <div className="menu-wrapper">
      
      {/* 项目信息 Card */}
      <div className="menu-project-info">
        <Card
          size="small"
          bordered={false}
          style={{ height: "100%", boxShadow: "0 1px 2px rgba(0,0,0,0.08)" }}
        >
          {/* ⭐ 继续传递 user + projectName */}
          <ProjectInfo user={user} projectName={projectName} />
        </Card>
      </div>

      {/* 项目流程 Card */}
      <div className="menu-progress">
        <Card
          size="small"
          bordered={false}
          style={{ height: "100%", boxShadow: "0 1px 2px rgba(0,0,0,0.08)" }}
        >
          {/* ⭐ 继续传递 user + projectName */}
          <Progress user={user} projectName={projectName} />
        </Card>
      </div>

    </div>
  );
}
