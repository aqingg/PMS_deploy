import React, { useState, useContext, useEffect } from "react";
import { Row, Col, Input, Divider, message } from "antd";
import StatisticBar from "./StatisticBar";
import PieChartStatistic from "./PieChartStatistic";
import ProjectList from "./ProjectList";
import "./index.css";

import { AppContext } from "../../context/AppContext";

const { Search } = Input;

export default function ProjectSummary() {
  const { projectRefreshFlag } = useContext(AppContext);

  const [searchText, setSearchText] = useState("");

  // =====================================================
  // 这里不再负责刷新，只负责 UI 提示（可选）
  // =====================================================
  useEffect(() => {
    if (projectRefreshFlag > 0) {
      message.info("Project list updated automatically");
    }
  }, [projectRefreshFlag]);

  return (
    <div className="project">
      {/* SearchBar */}
      <Row>
        <Col className="project-title" span={10}>
          My Projects
        </Col>
        <Col span={14}>
          <Search
            className="project-right"
            placeholder="Input Project Filter"
            onSearch={(v) => setSearchText(v.trim().toLowerCase())}
            enterButton
          />
        </Col>
      </Row>

      <Divider style={{ margin: "8px 0" }}/>

      {/* 统计信息 */}
      <Row align="middle" style={{ marginBottom: 10 }}>
        <Col flex="2">
          <div style={{ padding: "10px 20px" }}>
            <StatisticBar compact />
          </div>
        </Col>

        <Col flex="1" style={{ textAlign: "center", paddingTop: 10 }}>
          <PieChartStatistic width={220} height={220} />
        </Col>
      </Row>
      <Divider style={{ margin: "0 0" }}/>

      {/* 项目列表 */}
      <Row style={{ flex: 1, minHeight: 0 }}>
        <Col span={24} style={{ height: "100%" }}>
          <div style={{ height: "100%", overflow: "auto" }}>
            <ProjectList searchText={searchText} />
          </div>
        </Col>
      </Row>
    </div>
  );
}
