import React, { Component } from 'react';
import axios from "axios";
import { Typography, Tree, Space } from 'antd';
import {
  CheckCircleOutlined,
  PauseCircleOutlined,
  MinusCircleOutlined,
  SyncOutlined,
  ProjectOutlined
} from '@ant-design/icons';

import ProgressBar from '../ProgressBar';

let globalId = 0;
const genKey = () => `task-${globalId++}`;

const { Title, Text } = Typography;

export default class Progress extends Component {

  constructor(props) {
    super(props);

    this.state = {
      taskTree: [],
      loading: true
    };
  }

  // ⭐ 新增：外部可调用的刷新函数
  // ⭐ 新增：外部可调用的刷新函数（仍然可用）
rewriteDepartmentProgress = async () => {
  console.log("🔄 正在刷新 Project Progress ...");
  await this.fetchProjectProgress();  
};

// ⭐ 使用 FAKE DATA 替代后端请求（无参数检查）
fetchProjectProgress = async () => {
  try {
    const { user, projectName } = this.props;

    console.log("📡 Progress 使用假数据，不调用后端");
    console.log("Fake user =", user);
    console.log("Fake projectName =", projectName);

    // ======== ⭐ FAKE TREE（保持后端格式一致） ========
    const fakeTree = [
      {
        taskName: "Initial Design",
        status: this.randomStatus(),
        children: [
          { taskName: "Requirement Draft", status: this.randomStatus() },
          { taskName: "User Flow", status: this.randomStatus() }
        ]
      },
      {
        taskName: "Development",
        status: this.randomStatus(),
        children: [
          { taskName: "Frontend", status: this.randomStatus() },
          { taskName: "Backend", status: this.randomStatus() },
          { taskName: "API Integration", status: this.randomStatus() }
        ]
      },
      {
        taskName: "Testing",
        status: this.randomStatus(),
        children: [
          { taskName: "Unit Test", status: this.randomStatus() },
          { taskName: "Integration Test", status: this.randomStatus() }
        ]
      }
    ];

    // 模拟后端 200–400ms 延迟
    setTimeout(() => {
      globalId = 0; // reset key

      this.setState({
        taskTree: fakeTree,
        loading: false
      });
    }, 300);

  } catch (error) {
    console.error("❌ Progress 生成假数据失败:", error);

    this.setState({
      taskTree: [],
      loading: false
    });
  }
};



  // ⭐ 挂载时首次请求
  async componentDidMount() {
    await this.fetchProjectProgress();
  }

  // ⭐ 状态图标
  getStatusIcon = (status) => {
    switch (status) {
      case "Done":
        return <CheckCircleOutlined style={{ color: "#52c41a", fontSize: 16 }} />;
      case "Pending":
        return <PauseCircleOutlined style={{ color: "#b9900aff", fontSize: 16 }} />;
      case "Decline":
        return <MinusCircleOutlined style={{ color: "#707070ff", fontSize: 16 }} />;
      case "Ongoing":
        return <SyncOutlined spin style={{ color: "#1677ff", fontSize: 16 }} />;
      default:
        return null;
    }
  };

  // ⭐ DFS 统计数量
  countTasks = (node) => {
    let total = 1;
    let done = node.status === "Done" ? 1 : 0;
    let decline = node.status === "Decline" ? 1 : 0;

    if (node.children) {
      node.children.forEach(child => {
        const result = this.countTasks(child);
        total += result.total;
        done += result.done;
        decline += result.decline;
      });
    }

    return { total, done, decline };
  };

  // ⭐ 整体统计
  getOverallProgress = () => {
    const { taskTree } = this.state;
    let total = 0, done = 0, decline = 0;

    taskTree.forEach(root => {
      const result = this.countTasks(root);
      total += result.total;
      done += result.done;
      decline += result.decline;
    });

    return total === 0 ? 0 : Math.round(((done + decline) / total) * 100);
  };
  // ⭐ 随机生成任务状态
randomStatus = () => {
  const statuses = ["Done", "Pending", "Decline", "Ongoing"];
  return statuses[Math.floor(Math.random() * statuses.length)];
};
  // ⭐ 转换 Tree Data
  convertToTreeData = (data) => {
    return data.map((item) => ({
      key: genKey(),
      icon: this.getStatusIcon(item.status),
      title: item.taskName,
      children: item.children ? this.convertToTreeData(item.children) : []
    }));
  };

  render() {
    const { taskTree, loading } = this.state;

    if (loading) {
      return <div>Loading Progress...</div>;
    }

    const treeData = this.convertToTreeData(taskTree);
    const overallProgress = this.getOverallProgress();

    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "16px", height: "100%" }}>

        <Title level={4} style={{ margin: 0 }}>
          Project Detail
        </Title>

        <Space direction="vertical" size={4} style={{ width: "100%" }}>
          <Text type="secondary" style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 4 }}>
            <ProjectOutlined /> Whole Project Progress
          </Text>

          <ProgressBar percent={overallProgress} />
        </Space>

        <div style={{ overflow: "auto", flex: 1 }}>
          <Tree
            showIcon
            defaultExpandAll
            treeData={treeData}
            onSelect={(keys, info) => {
              const taskName = info.node.title;
              window.location.hash = `#/task/${taskName}`;
            }}
          />
        </div>
      </div>
    );
  }
}
