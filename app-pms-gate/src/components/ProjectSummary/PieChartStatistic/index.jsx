import React, { useContext, useEffect, useState } from "react";
import { PieChart, Pie, Cell, Tooltip } from "recharts";
import { AppContext } from "../../../context/AppContext";

const COLORS = ["#868686ff", "#5072fbff", "#4cc372ff"];

export default function PieChartStatistic() {
  const { getProjectTagList } = useContext(AppContext);
  const [data, setData] = useState([]);

  useEffect(() => {
    async function loadStats() {
      const s = await getProjectTagList();
      setData([
        { name: "Quotation", value: s.Quotation },
        { name: "Running", value: s.Running },
        { name: "SOP", value: s.SOP },
      ]);
    }
    loadStats();
  }, [getProjectTagList]);

  return (
    <PieChart width={260} height={260}>
      <Pie
        data={data}
        cx="50%"
        cy="50%"
        outerRadius={95}
        dataKey="value"
        label
      >
        {data.map((entry, i) => (
          <Cell key={i} fill={COLORS[i % COLORS.length]} />
        ))}
      </Pie>

      {/* 只保留鼠标 hover 提示，更干净 */}
      <Tooltip />
    </PieChart>
  );
}
