import React, { Component } from 'react';
import { Row, Col, Tag, Progress, Tooltip, Typography } from 'antd';
import ProjectSidebar from './ProjectSidebar';
import './index.css';

export default class ProjectItem extends Component {
  state = { hovering: false };

  render() {
    const { value, onAction } = this.props;
    const { hovering } = this.state;

    // ----------- 背景色逻辑（与 TodoItem 完全一致） -----------
    let bgColor = "transparent";

    // 100% → 淡灰色（完成）
    if (value.rating === 1) {
      bgColor = "rgba(200, 200, 200, 0.25)";
    }

    // Hover 优先级最高 → 蓝色背景
    if (hovering) {
      bgColor = "rgba(230, 247, 255, 0.5)";
    }

    return (
      <div
        style={{ height: 60, position: "relative" }}
        onMouseEnter={() => this.setState({ hovering: true })}
        onMouseLeave={() => this.setState({ hovering: false })}
      >
        {/* Sidebar 左侧浮动与动画 */}
        {hovering && (
          <div
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              height: "100%",
              zIndex: 99,
              pointerEvents: "none"
            }}
          >
            <div style={{ pointerEvents: "auto" }}>
              <ProjectSidebar onAction={onAction} itemKey={value.key} />
            </div>
          </div>
        )}

        {/* 主体内容 */}
        <Row
          align="middle"
          onClick={() => onAction("openProject", value.key)}
          style={{
            height: '100%',
            padding: '8px 12px',
            borderRadius: 4,
            backgroundColor: bgColor,
            boxShadow: hovering ? '0 2px 8px rgba(0,0,0,0.15)' : 'none',
            transition: 'all 0.2s',
            position: 'relative',

            paddingLeft: 12,
            paddingRight: 12, 
          }}
        >
          {/* 进度条 */}
          <Col span={2}>
            <Progress
              percent={Math.round((value.progress ?? 0) * 100)}
              size="small"
              showInfo={false}
              style={{ width: '75%' }}
              strokeColor={value.progress === 1 ? "green" : undefined}
            />
          </Col>

          {/* Project 名称 */}
          <Col span={6}>
                {value.projectName}
          </Col>

          {/* Comment */}
          <Col span={10}>
            <Tooltip title={value.comment}>
              <Typography.Text ellipsis>
                {value.comment}
              </Typography.Text>
              </Tooltip>
          </Col>

          {/* Tags */}
          <Col span={6} style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {value.tags?.map(tag => (
              <Tag color="blue" key={tag}>{tag}</Tag>
            ))}
          </Col>
        </Row>
      </div>
    );
  }
}
