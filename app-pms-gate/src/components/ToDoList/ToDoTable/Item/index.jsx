import React, { Component } from "react";
import { Row, Col, Tag, Tooltip, Progress } from "antd";

import Sidebar from "./Sidebar";
import dayjs from "dayjs";
import { AppContext } from "../../../../context/AppContext";
import "./index.css";
/**
 * Todo Item (V2)
 *
 * 只做展示 + 意图转发
 */
export default class Item extends Component {
  static contextType = AppContext;
  state = { hovering: false };

  render() {
    const { user, teamMembers } = this.context;
    const currentUserId = user?.username;

    const getUserNameByAccount = (account) => {
      if (!account || !Array.isArray(teamMembers)) return account;
      const u = teamMembers.find(m => m.account === account);
      return u?.name || account;
    };

    const calcAssigneeProgress = (progressMap, userId) => {
      if (!progressMap || !userId) return 0;
      const v = progressMap[userId];
      return typeof v === "number" ? v : 0;
    };

  const calcCreatorProgress = (progressMap, assigneeIds, creatorId) => {
    if (!progressMap) return 0;

    // ⭐ 没有 assignee，creator 自己就是唯一执行人
    if (!assigneeIds || assigneeIds.length === 0) {
      const v = progressMap[creatorId];
      return typeof v === "number" ? v : 0;
    }

    const values = assigneeIds
      .map(uid => progressMap[uid])
      .filter(v => typeof v === "number");

    if (!values.length) return 0;

    return Math.round(
      values.reduce((a, b) => a + b, 0) / values.length
    );
  };

    const { value: todo, onAction } = this.props;
    const { hovering } = this.state;

    /** =========================
     * Status → UI 映射
     * ========================= */
    const STATUS_UI = {
      pending: {
        progress: 0,
        strokeColor: undefined,
        bg: "transparent"
      },
      ongoing: {
        progress: 50,
        strokeColor: undefined,
        bg: "rgba(230, 247, 255, 0.3)"
      },
      done: {
        progress: 100,
        strokeColor: "green",
        bg: "rgba(200, 200, 200, 0.25)"
      }
    };

  const isCreator = todo.creator_id === currentUserId;

  const displayProgress = isCreator
    ? calcCreatorProgress(todo.progress, todo.assignee_ids, todo.creator_id)
    : calcAssigneeProgress(todo.progress, currentUserId);

  let statusUI;
  if (displayProgress >= 100) {
    statusUI = STATUS_UI.done;
  } else if (displayProgress > 0) {
    statusUI = STATUS_UI.ongoing;
  } else {
    statusUI = STATUS_UI.pending;
  }
    /** =========================
     * Due / Overdue 计算
     * ========================= */
    const today = dayjs().startOf("day");
    const due = dayjs(todo.due_date);
    const isOverdue =
      due.isBefore(today) &&
      displayProgress < 100;
      
    const daysToDue = due.diff(today, "day");
    const isDueSoon =
      !isOverdue &&
      daysToDue >= 0 &&
      daysToDue <= 2 &&
      displayProgress < 100;

    const isAssignedFromOthers =
      todo.creator_id &&
      todo.creator_id !== currentUserId;

    /** =========================
     * Hover 样式
     * ========================= */
    let bgColor = statusUI.bg;
    if (hovering) {
      bgColor = "rgba(230, 247, 255, 0.5)";
    }

    const calcFinishedCount = (progressMap, assigneeIds) => {
      if (!progressMap || !Array.isArray(assigneeIds)) {
        return { finished: 0, total: 0 };
      }

      const total = assigneeIds.length;

      const finished = assigneeIds.filter(
        uid => progressMap[uid] >= 100
      ).length;

      return { finished, total };
    };

    const isMultiAssigned =
      isCreator &&
      Array.isArray(todo.assignee_ids) &&
      todo.assignee_ids.length > 1;

    const { finished, total } = isMultiAssigned
      ? calcFinishedCount(todo.progress, todo.assignee_ids)
      : { finished: 0, total: 0 };

    const showFinishedSummary =
      isMultiAssigned && total > 0;

    return (
      <div
        style={{ height: "60px", position: "relative" }}
        onMouseEnter={() => this.setState({ hovering: true })}
        onMouseLeave={() => this.setState({ hovering: false })}
      >
        {/* Sidebar */}
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
              <Sidebar
                todoId={todo.id}
                hasLink={!!todo.link}
                onAction={onAction}
                canEdit={isCreator}
                canDelete={isCreator}
              />
            </div>
          </div>
        )}

        {/* Main Row */}
        <Row
          align="middle"
          style={{
            height: "100%",
            padding: "8px 12px",
            borderRadius: 4,
            backgroundColor: bgColor,
            boxShadow: hovering ? "0 2px 8px rgba(0,0,0,0.15)" : "none",
            transition: "all 0.2s",
            position: "relative",
            paddingLeft: 12,
            paddingRight: 12
          }}
        >
          {/* Title */}
          <Col span={3}>
          <div className="todo-comment-ellipsis">
            {todo.title}
          </div>
          </Col>

          {/* Progress */}
          <Col span={3} style={{ textAlign: "center" }}>
            <Progress
              type="circle"
              percent={displayProgress}
              size={30}
              status={displayProgress >= 100 ? "success" : "normal"}
              format={displayProgress >= 100 ? undefined : () => ""}
            />
          </Col>
          {/* Comment */}
          <Col span={9}>
            <Tooltip title={todo.comment}>
              <div className="todo-comment-ellipsis">
                {todo.comment}
              </div>
            </Tooltip>
          </Col>

          {/* Due Date */}
          <Col span={3}>          
            <div className="todo-comment-ellipsis">
              {todo.due_date}
            </div>
          </Col>

          {/* Tags */}
          <Col span={6} style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {todo.tags?.map((tag) => (
              <Tag color="blue" key={tag}>
                {tag}
              </Tag>
            ))}

            {isOverdue && (
              <Tag color="red">
                Overdue
              </Tag>
            )}

            {isDueSoon && (
              <Tag color="orange">
                Due in {daysToDue} D
              </Tag>
            )}

            {isAssignedFromOthers && (
              <Tag color="purple">
                From {getUserNameByAccount(todo.creator_id)}
              </Tag>
            )}

            {showFinishedSummary && (
              <Tag color={finished === total ? "green" : "geekblue"}>
                {finished} / {total} Finished
              </Tag>
            )}

          </Col>
        </Row>
      </div>
    );
  }
}
