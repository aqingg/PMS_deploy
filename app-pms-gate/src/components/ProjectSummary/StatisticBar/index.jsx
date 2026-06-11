import React, { useContext, useEffect, useState } from "react";
import { Statistic, Row, Col } from "antd";
import { AppContext } from "../../../context/AppContext";

export default function StatisticBar() {
  const { getProjectTagList } = useContext(AppContext);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    getProjectTagList().then((res) => setStats(res));
  }, [getProjectTagList]);

  if (!stats) return null;

  const items = [
    { title: "My Projects", value: stats.myProjects },
    { title: "Quotation", value: stats.Quotation },
    { title: "Running", value: stats.Running },
    { title: "SOP", value: stats.SOP },
  ];

  return (
      <Row gutter={[24, 24]}>
        {items.map((item) => (
          <Col span={12} key={item.title}>
            <Statistic
              title={item.title}
              value={item.value}
              suffix={`/ ${stats.total}`}
              valueStyle={{ fontSize: 26 }}
            />
          </Col>
        ))}
      </Row>
  );
}
