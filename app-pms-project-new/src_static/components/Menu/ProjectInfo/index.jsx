import React, { Component } from 'react';
import { Typography, Button, Space } from 'antd';
import { EditOutlined, FormOutlined } from '@ant-design/icons';
import ProgressBar from '../ProgressBar';
import axios from 'axios';

const { Title, Text } = Typography;

export default class ProjectInfo extends Component {
  state = {
    projectProgress: 0,
  };

  componentDidMount() {
  this.loadProgress();
  window.addEventListener("hashchange", this.loadProgress);
}

componentWillUnmount() {
  window.removeEventListener("hashchange", this.loadProgress);
}

  componentDidUpdate(prevProps) {
    if (prevProps.projectName !== this.props.projectName) {
      this.loadProgress();  // 项目切换 → 自动刷新
    }
  }

  // ⭐ 自动刷新项目进度（假数据版）
  loadProgress = async () => {
    const { user, projectName } = this.props;
    if (!user || !projectName) return;

    // --- 这里是假数据，模拟后端返回 ---
    const fakeResponse = { projectInfoRate: 85 };

    // 模拟网络延迟（可选）
    setTimeout(() => {
      this.setState({
        projectProgress: fakeResponse.projectInfoRate
      });
    }, 300);
  };


  handleEdit = () => {
    window.location.hash = "#/edit";
  };

  render() {
    return (
      <div style={{ display: "flex", flexDirection: "column", height: "100%", gap: "16px" }}>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <Title level={4} style={{ margin: 0 }}>
            Dummy Project
          </Title>

          <Button type="text" icon={<EditOutlined />} onClick={this.handleEdit}>
            Edit
          </Button>
        </div>

        <Space direction="vertical" size={4} style={{ width: "100%" }}>
          <Text type="secondary" style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 4 }}>
            <FormOutlined /> Completeness of project information
          </Text>
          <ProgressBar percent={80} />
        </Space>

      </div>
    );
  }
}
