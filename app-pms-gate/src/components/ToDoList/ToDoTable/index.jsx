import React, {
  useContext,
  useState,
  useRef,
  useMemo,
  useEffect,
} from "react";
import dayjs from "dayjs";
import {
  FloatButton,
  Modal,
  Form,
  Input,
  DatePicker,
  Button,
  Select,
  Progress,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import "./index.css";

import {
  DragDropContext,
  Droppable,
  Draggable,
} from "react-beautiful-dnd";

import { AppContext } from "../../../context/AppContext";
import Item from "./Item";

const matchTodoByKeyword = (todo, keyword) => {
  if (!keyword) return true;

  const k = keyword.toLowerCase();

  const inTitle = todo.title?.toLowerCase().includes(k);
  const inComment = todo.comment?.toLowerCase().includes(k);

  const inTags = Array.isArray(todo.tags)
    ? todo.tags.some(tag =>
        tag.toLowerCase().includes(k)
      )
    : false;

  return inTitle || inComment || inTags;
};


export default function ToDoTable({ searchText }) {

  const {
    todos,
    user,
    teamMembers,
    createTodoV2,
    updateTodoV2,
    deleteTodoV2,
    reorderTodosV2,
    openTodoLink,
  } = useContext(AppContext);

  /** =========================
   * UI State
   * ========================= */
  const [showAdd, setShowAdd] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const [editingTodo, setEditingTodo] = useState(null);
  const [form] = Form.useForm();
  const ALL_VALUE = "__ALL__";


  /** =========================
   * Drag state
   * ========================= */
  const isDraggingRef = useRef(false);

  /** =========================
   * Local display state
   * ========================= */
  const [displayTodos, setDisplayTodos] = useState([]);

  /** 同步外部 todos → displayTodos（非拖拽时） */
  useEffect(() => {
    if (!isDraggingRef.current) {
      setDisplayTodos(todos);
    }
  }, [todos]);

  const editFormRef = useRef(null);

  /** =========================
   * Filter (UI only)
   * ========================= */
  const searchedTodos = useMemo(() => {
    return displayTodos.filter(todo =>
      matchTodoByKeyword(todo, searchText)
    );
  }, [displayTodos, searchText]);

  /** =========================
   * Drag & Reorder
   * ========================= */
  const onDragStart = () => {
    isDraggingRef.current = true;
  };

  const onDragEnd = (result) => {
    isDraggingRef.current = false;
    if (!result.destination) return;

    const newList = Array.from(searchedTodos);
    const [moved] = newList.splice(result.source.index, 1);
    newList.splice(result.destination.index, 0, moved);

    setDisplayTodos(newList);

    reorderTodosV2(
      newList.map((t, idx) => ({
        id: t.id,
        order_index: idx,
      }))
    );
  };

  /** =========================
   * Sidebar action handler
   * ========================= */
  const handleAction = (action, todoId) => {
    const todo = displayTodos.find((t) => t.id === todoId);
    if (!todo) return;

    switch (action) {
      case "edit":
        setEditingTodo(todo);
        setShowEdit(true);
        setTimeout(() => {
          editFormRef.current?.setFieldsValue({
            title: todo.title,
            due_date: dayjs(todo.due_date),
            comment: todo.comment,
            tags: todo.tags?.join(", "),
            link: todo.link,
            assignee_ids: todo.assignee_ids,
          });
        }, 0);
        break;

      case "open_link":
        if (todo.link) {
          openTodoLink(todo.link);
        }
        break;

      case "delete":
        deleteTodoV2(todoId);
        break;

      case "pending":
        updateTodoV2(todoId, {
              progress: { [user.username]: 0 }
        });
        break;

      case "ongoing":
        updateTodoV2(todoId, {
              progress: { [user.username]: 50 }
        });
        break;

      case "done":
        updateTodoV2(todoId, {
              progress: { [user.username]: 100 }
        });
        break;

      default:
        break;
    }
  };

  const renderUserWithProgress = (userId, label) => {
    if (!editingTodo?.progress) {
      return <span>{label}</span>;
    }

    const percent =
      typeof editingTodo.progress[userId] === "number"
        ? editingTodo.progress[userId]
        : 0;

    return (
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <Progress
          type="circle"
          percent={percent}
          size={16}
          strokeWidth={12}
          status={percent >= 100 ? "success" : "normal"}
        />
        <span>{label}</span>
      </div>
    );
  };


  return (
    <div className="todo-table-container">
      <div className="todo-table-wrapper">
        <div className="todo-table-header">
          <div className="header-row">
            <div className="col col-title">Title</div>
            <div className="col col-progress">Progress</div>
            <div className="col col-comment">Comment</div>
            <div className="col col-date">Due Date</div>
            <div className="col col-tags">Tags</div>
          </div>
        </div>

        <DragDropContext onDragStart={onDragStart} onDragEnd={onDragEnd}>
          <Droppable droppableId="todoList">
            {(provided) => (
              <div ref={provided.innerRef} {...provided.droppableProps}>
                {searchedTodos.map((todo, idx) => (
                  <Draggable
                    key={todo.id}
                    draggableId={String(todo.id)}
                    index={idx}
                  >
                    {(provided) => (
                      <div
                        ref={provided.innerRef}
                        {...provided.draggableProps}
                        {...provided.dragHandleProps}
                      >
                        <Item value={todo} onAction={handleAction} />
                      </div>
                    )}
                  </Draggable>
                ))}
                {provided.placeholder}
              </div>
            )}
          </Droppable>
        </DragDropContext>
      </div>

      {/* Floating Button */}
      <div className="todo-float-buttons">
        <FloatButton
          icon={<PlusOutlined />}
          tooltip="New Todo"
          onClick={() => setShowAdd(true)}
        />
      </div>

      {/* Edit Modal */}
      <Modal
        title="Edit Todo"
        open={showEdit}
        onCancel={() => setShowEdit(false)}
        footer={null}
      >
        <Form
          ref={editFormRef}
          layout="vertical"
          onFinish={(values) => {
            updateTodoV2(editingTodo.id, {
              title: values.title,
              due_date: values.due_date.format("YYYY-MM-DD"),
              comment: values.comment,
              tags: values.tags
                ? values.tags.split(",").map((t) => t.trim())
                : [],
              operator_id: user.username,
              link: values.link || "",
              assignee_ids: values.assignee_ids,
            });
            setShowEdit(false);
          }}
        >
          <Form.Item name="title" label="Title" rules={[{ required: true }]}>
            <Input />
          </Form.Item>

          <Form.Item
            name="due_date"
            label="Due Date"
            rules={[{ required: true }]}
          >
            <DatePicker style={{ width: "100%" }} />
          </Form.Item>

          <Form.Item name="tags" label="Tags">
            <Input />
          </Form.Item>

          <Form.Item name="comment" label="Comment">
            <Input.TextArea rows={3} />
          </Form.Item>

          <Form.Item
            name="assignee_ids"
            label="Assign To"
            tooltip="Re-assign this task to others"
          >
            <Select
              mode="multiple"
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="Select user"
              onChange={(values) => {
                if (values.includes(ALL_VALUE)) {
                  const allAccounts = teamMembers.map((m) => m.account);
                  editFormRef.current?.setFieldsValue({
                    assignee_ids: allAccounts,
                  });
                }
              }}
              options={[
                { label: "All Team Members", value: ALL_VALUE },
                ...teamMembers.map((m) => ({
                  label: `${m.name} (${m.account})`,
                  value: m.account,
                })),
              ]}

              /* ========= 下拉列表 ========= */
              optionRender={(option) => {
                if (option.value === ALL_VALUE) {
                  return <span>{option.label}</span>;
                }
                return renderUserWithProgress(option.value, option.label);
              }}

              /* ========= 已选 tag ========= */
              tagRender={(tagProps) => {
                const { value, label, closable, onClose } = tagProps;

                if (value === ALL_VALUE) {
                  return (
                    <span style={{ marginRight: 4 }}>
                      {label}
                    </span>
                  );
                }

                return (
                  <div
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                      paddingRight: 4,
                    }}
                  >
                    {renderUserWithProgress(value, label)}
                    {closable && (
                      <span
                        onClick={onClose}
                        style={{
                          cursor: "pointer",
                          marginLeft: 2,
                        }}
                      >
                        ×
                      </span>
                    )}
                  </div>
                );
              }}
            />
          </Form.Item>

          <Form.Item name="link" label="Link">
            <Input />
          </Form.Item>

          <Button type="primary" htmlType="submit" block>
            Update
          </Button>
        </Form>
      </Modal>

      {/* Add Modal */}
      <Modal
        title="New Todo"
        open={showAdd}
        onCancel={() => setShowAdd(false)}
        footer={null}
      >
         <Form
          form={form}
          layout="vertical"
          onFinish={(values) => {
            createTodoV2({
              title: values.title,
              due_date: values.due_date.format("YYYY-MM-DD"),
              comment: values.comment,
              link: values.link || "",
              tags: values.tags
                ? values.tags.split(",").map((t) => t.trim())
                : [],
              assignee_ids: values.assignee_ids?.length
                ? values.assignee_ids
                : [user.username],
              operator_id: user.username,
            });
            setShowAdd(false);
          }}
        >
          <Form.Item name="title" label="Title" rules={[{ required: true }]}>
            <Input />
          </Form.Item>

          <Form.Item
            name="due_date"
            label="Due Date"
            rules={[{ required: true }]}
          >
            <DatePicker style={{ width: "100%" }} />
          </Form.Item>

          <Form.Item name="tags" label="Tags">
            <Input />
          </Form.Item>

          <Form.Item name="comment" label="Comment">
            <Input.TextArea rows={3} />
          </Form.Item>

          <Form.Item
            name="assignee_ids"
            label="Order for others"
            tooltip="Leave empty to create for yourself"
          >
          <Select
            mode="multiple"
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="Select user"
            onChange={(values) => {
              if (values.includes(ALL_VALUE)) {
                const allAccounts = teamMembers.map((m) => m.account);
                // 重新设置成全选的真实值
                form.setFieldsValue({ assignee_ids: allAccounts });
              }
            }}
            options={[
              { label: "All Team Members", value: ALL_VALUE },
              ...teamMembers.map((m) => ({
                label: `${m.name} (${m.account})`,
                value: m.account,
              })),
            ]}
          />

          </Form.Item>

          <Form.Item
            name="link"
            label="Link"
            tooltip="Optional external reference (URL, document, issue, etc.)"
          >
            <Input />
          </Form.Item>

          <Button type="primary" htmlType="submit" block>
            Create
          </Button>
        </Form>
      </Modal>
    </div>
  );
}
